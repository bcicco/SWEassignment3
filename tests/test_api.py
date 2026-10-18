from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from swe.api import create_app
from swe.app import DeliveryManagementSystem
from swe.domain.shared.ids import now
from swe.domain.user import Customer, DeliveryStaff, StaffMember
from swe.events import handlers

CUSTOMER = {"X-User-Id": "cust-1"}
OTHER_CUSTOMER = {"X-User-Id": "cust-2"}
STAFF = {"X-User-Id": "staff-1"}
DRIVER = {"X-User-Id": "driver-1"}
OTHER_DRIVER = {"X-User-Id": "driver-2"}

DETAILS = {
    "contact_name": "Sam",
    "contact_phone": "0400000000",
    "parcels": [{"size": "small", "weight_kg": "2.5"}],
    "pickup_address": {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
    "dropoff_address": {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
}


@pytest.fixture
def api(repo, monkeypatch):
    dms = DeliveryManagementSystem(repo)
    for user in [
        Customer(user_id="cust-1", name="Sam", phone="0400000000"),
        Customer(user_id="cust-2", name="Jo", phone="0400000000"),
        StaffMember(user_id="staff-1", name="Alex", phone="0411111111"),
        DeliveryStaff(user_id="driver-1", name="Lee", phone="0422222222"),
        DeliveryStaff(user_id="driver-2", name="Kim", phone="0433333333"),
    ]:
        dms.users.add(user)
    monkeypatch.setattr(handlers, "system", lambda: dms)  # for run_job_handler
    return TestClient(create_app(dms))


# stands in for the stream -> EventBridge -> create-delivery-job Lambda hop
def run_job_handler(accepted: dict) -> None:
    handlers.create_delivery_job({"detail": accepted})


def log(api, headers=CUSTOMER, **overrides) -> str:
    response = api.post("/requests", json=DETAILS | overrides, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["request_id"]


def issue(api, request_id, price="50") -> str:
    t = now()
    window = lambda start, end: [(t + timedelta(hours=start)).isoformat(), (t + timedelta(hours=end)).isoformat()]  # noqa: E731
    body = {"price": price, "eta_pickup": window(1, 3), "eta_dropoff": window(4, 6)}
    response = api.post(f"/requests/{request_id}/quotes", json=body, headers=STAFF)
    assert response.status_code == 201, response.text
    return response.json()["quote_id"]


def test_full_flow(api):
    request_id = log(api)
    quote_id = issue(api, request_id)

    response = api.post(f"/requests/{request_id}/quotes/{quote_id}/accept", headers=CUSTOMER)
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["event_type"] == "quote_accepted"
    assert api.get(f"/jobs/{accepted['job_id']}", headers=CUSTOMER).status_code == 404  # not created yet
    run_job_handler(accepted)
    assert api.get(f"/jobs/{accepted['job_id']}", headers=CUSTOMER).json()["job"]["state"] == "unallocated"

    detail = api.get(f"/requests/{request_id}", headers=CUSTOMER).json()
    assert detail["request"]["status"] == "accepted"
    assert detail["quotes"][0]["status"] == "accepted"
    assert [e["event_type"] for e in detail["history"]] == [
        "request_logged",
        "quote_issued",
        "quote_accepted",
        "job_created",
    ]
    assert detail["history"][1]["price"] == "50"  # each event keeps its own fields


def test_identity_comes_from_headers_not_the_body(api):
    request_id = log(api, customer_id="someone-else")
    request = api.get(f"/requests/{request_id}", headers=CUSTOMER).json()["request"]
    assert request["customer_id"] == "cust-1"
    assert request["logged_by"] is None


def test_staff_log_for_a_caller(api):
    anonymous = log(api, headers=STAFF)
    for_customer = log(api, headers=STAFF, customer_id="cust-1")
    requests = {r["request_id"]: r for r in api.get("/requests", headers=STAFF).json()}
    assert requests[anonymous]["customer_id"] is None
    assert requests[anonymous]["logged_by"] == "staff-1"
    assert requests[for_customer]["customer_id"] == "cust-1"


def test_customers_see_only_their_own_requests(api):
    mine, theirs = log(api), log(api, headers=OTHER_CUSTOMER)
    assert [r["request_id"] for r in api.get("/requests", headers=CUSTOMER).json()] == [mine]
    assert {r["request_id"] for r in api.get("/requests", headers=STAFF).json()} == {mine, theirs}
    assert api.get(f"/requests/{theirs}", headers=CUSTOMER).status_code == 403
    assert api.post(f"/requests/{theirs}/cancel", headers=CUSTOMER).status_code == 403


def test_roles_are_enforced(api):
    request_id = log(api)
    quote_id = issue(api, request_id)
    body = {"price": "60", "eta_pickup": [], "eta_dropoff": []}
    assert api.post(f"/requests/{request_id}/quotes", json=body, headers=CUSTOMER).status_code == 403
    assert api.post(f"/requests/{request_id}/quotes/{quote_id}/accept", headers=STAFF).status_code == 403
    assert api.post(f"/requests/{request_id}/quotes/{quote_id}/accept", headers=OTHER_CUSTOMER).status_code == 403


def test_identity_headers_are_required(api):
    assert api.get("/requests").status_code == 422


def test_role_comes_from_the_account_not_the_client(api):
    # a client claiming a role it doesn't have gets nothing for it
    staff_claim = {"X-User-Id": "cust-1", "X-User-Role": "staff"}
    assert api.post(f"/requests/{log(api)}/quotes", json={}, headers=staff_claim).status_code == 403
    assert api.post(f"/requests/{log(api)}/quotes", json={}, headers=DRIVER).status_code == 403


def test_unknown_callers_are_refused(api):
    assert api.get("/requests", headers={"X-User-Id": "nobody"}).status_code == 403


def test_refused_rules_are_400(api):
    same = DETAILS["pickup_address"]
    assert api.post("/requests", json=DETAILS | {"dropoff_address": same}, headers=CUSTOMER).status_code == 400

    request_id = log(api)
    quote_id = issue(api, request_id)
    issue(api, request_id)  # supersedes the first quote
    response = api.post(f"/requests/{request_id}/quotes/{quote_id}/accept", headers=CUSTOMER)
    assert response.status_code == 400
    assert "not the current quote" in response.json()["detail"]


def test_reject_and_cancel(api):
    request_id = log(api)
    first = issue(api, request_id)
    assert api.post(f"/requests/{request_id}/quotes/{first}/reject", headers=CUSTOMER).json()["status"] == "rejected"
    second = issue(api, request_id)
    assert api.post(f"/requests/{request_id}/quotes/{second}/revision", headers=CUSTOMER).status_code == 404
    assert api.post(f"/requests/{request_id}/cancel", headers=CUSTOMER).json()["status"] == "cancelled"
    assert api.post(f"/requests/{request_id}/cancel", headers=STAFF).status_code == 400


def test_unknown_request_is_404(api):
    assert api.get("/requests/nope", headers=STAFF).status_code == 404


def test_conflict_is_409(api, repo, monkeypatch):
    request_id = log(api)
    stale = repo.get_request(request_id)  # still open
    api.post(f"/requests/{request_id}/cancel", headers=CUSTOMER)
    monkeypatch.setattr(repo, "get_request", lambda _: stale)  # a second cancel decided on the stale copy
    assert api.post(f"/requests/{request_id}/cancel", headers=STAFF).status_code == 409


def test_list_filters_by_status(api):
    kept, cancelled = log(api), log(api)
    api.post(f"/requests/{cancelled}/cancel", headers=CUSTOMER)
    for headers in (CUSTOMER, STAFF):
        assert [r["request_id"] for r in api.get("/requests?status=open", headers=headers).json()] == [kept]
        listed = api.get("/requests", headers=headers).json()
        assert [r["request_id"] for r in listed] == [cancelled, kept]  # every status, newest first


def accept(api, request_id, quote_id) -> str:
    response = api.post(f"/requests/{request_id}/quotes/{quote_id}/accept", headers=CUSTOMER)
    assert response.status_code == 202, response.text
    run_job_handler(response.json())
    return response.json()["job_id"]


def test_accepted_request_becomes_a_listed_job(api):
    request_id = log(api)
    quote_id = issue(api, request_id, price="42")
    job_id = accept(api, request_id, quote_id)

    for headers in (CUSTOMER, STAFF):
        [summary] = api.get("/jobs", headers=headers).json()
        assert (summary["job"]["job_id"], summary["request"]["request_id"]) == (job_id, request_id)
    assert [s["job"]["job_id"] for s in api.get("/jobs?state=unallocated", headers=STAFF).json()] == [job_id]
    assert api.get("/jobs?state=delivered", headers=STAFF).json() == []

    detail = api.get(f"/jobs/{job_id}", headers=CUSTOMER).json()
    assert detail["job"]["customer_id"] == "cust-1"
    assert (detail["quote"]["quote_id"], detail["quote"]["price"]) == (quote_id, "42")


def test_customers_see_only_their_own_jobs(api):
    request_id = log(api)
    job_id = accept(api, request_id, issue(api, request_id))
    assert api.get("/jobs", headers=OTHER_CUSTOMER).json() == []
    assert api.get(f"/jobs/{job_id}", headers=OTHER_CUSTOMER).status_code == 403
    assert api.get("/jobs/nope", headers=STAFF).status_code == 404


def test_drivers_manage_their_own_availability(api):
    t = now().replace(minute=0, second=0, microsecond=0)
    window = lambda start, end: [(t + timedelta(hours=start)).isoformat(), (t + timedelta(hours=end)).isoformat()]  # noqa: E731
    response = api.post("/availability", json={"window": window(1, 5)}, headers=DRIVER)
    assert response.status_code == 201, response.text
    slot_id = response.json()["id"]
    assert api.post("/availability", json={"window": window(4, 6)}, headers=DRIVER).status_code == 400  # overlaps
    assert [s["id"] for s in api.get("/availability", headers=DRIVER).json()] == [slot_id]

    # only drivers have availability
    assert api.post("/availability", json={"window": window(1, 5)}, headers=STAFF).status_code == 403
    assert api.get("/availability", headers=CUSTOMER).status_code == 403

    # office staff see who's free for a pickup window
    start, end = window(2, 3)
    available = api.get("/drivers/available", params={"start": start, "end": end}, headers=STAFF)
    assert [d["user_id"] for d in available.json()] == ["driver-1"]
    assert api.get("/drivers/available", params={"start": start, "end": end}, headers=DRIVER).status_code == 403

    assert api.delete(f"/availability/{slot_id}", headers=DRIVER).status_code == 204
    assert api.get("/availability", headers=DRIVER).json() == []
    assert api.delete(f"/availability/{slot_id}", headers=DRIVER).status_code == 404


def job_for(api) -> str:
    request_id = log(api)
    response = api.post(f"/requests/{request_id}/quotes/{issue(api, request_id)}/accept", headers=CUSTOMER)
    run_job_handler(response.json())
    return response.json()["job_id"]


def test_staff_allocate_and_reallocate_a_job(api):
    t = now()
    whole_day = {"window": [(t - timedelta(hours=1)).isoformat(), (t + timedelta(hours=10)).isoformat()]}
    for driver in (DRIVER, OTHER_DRIVER):
        assert api.post("/availability", json=whole_day, headers=driver).status_code == 201
    job_id = job_for(api)

    candidates = api.get(f"/jobs/{job_id}/candidates", headers=STAFF).json()
    assert [(c["driver"]["user_id"], c["load"]) for c in candidates] == [("driver-1", 0), ("driver-2", 0)]
    assert api.get(f"/jobs/{job_id}/candidates", headers=DRIVER).status_code == 403

    # only office staff allocate
    assert (
        api.post(f"/jobs/{job_id}/allocate", json={"delivery_staff_id": "driver-1"}, headers=DRIVER).status_code == 403
    )
    response = api.post(f"/jobs/{job_id}/allocate", json={"delivery_staff_id": "driver-1"}, headers=STAFF)
    assert response.status_code == 201, response.text
    again = api.post(f"/jobs/{job_id}/allocate", json={"delivery_staff_id": "driver-2"}, headers=STAFF)
    assert again.status_code == 400
    assert "already allocated to driver-1" in again.json()["detail"]

    # a driver sees only the jobs allocated to them, and no requests
    assert [s["job"]["job_id"] for s in api.get("/jobs", headers=DRIVER).json()] == [job_id]
    assert api.get(f"/jobs/{job_id}", headers=DRIVER).status_code == 200
    assert api.get(f"/jobs/{job_id}", headers=OTHER_DRIVER).status_code == 403
    assert api.get("/requests", headers=DRIVER).status_code == 403

    body = {"delivery_staff_id": "driver-2", "reason": "driver-1 is off sick"}
    assert api.post(f"/jobs/{job_id}/reallocate", json=body, headers=STAFF).status_code == 201
    assert api.get("/jobs", headers=DRIVER).json() == []
    detail = api.get(f"/jobs/{job_id}", headers=OTHER_DRIVER).json()
    assert detail["job"]["delivery_staff_id"] == "driver-2"
    assert [a["delivery_staff_id"] for a in detail["allocations"]] == ["driver-1", "driver-2"]
