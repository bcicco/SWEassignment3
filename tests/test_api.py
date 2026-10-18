from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from swe.api import create_app
from swe.app import DeliveryManagementSystem
from swe.domain.shared.ids import now

CUSTOMER = {"X-User-Id": "cust-1", "X-User-Role": "customer"}
OTHER_CUSTOMER = {"X-User-Id": "cust-2", "X-User-Role": "customer"}
STAFF = {"X-User-Id": "staff-1", "X-User-Role": "staff"}

DETAILS = {
    "contact_name": "Sam",
    "contact_phone": "0400000000",
    "parcels": [{"size": "small", "weight_kg": "2.5"}],
    "pickup_address": {"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
    "dropoff_address": {"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
}


@pytest.fixture
def api(repo):
    return TestClient(create_app(DeliveryManagementSystem(repo)))


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
    assert response.status_code == 201
    assert response.json()["state"] == "unallocated"

    detail = api.get(f"/requests/{request_id}", headers=CUSTOMER).json()
    assert detail["request"]["status"] == "accepted"
    assert detail["quotes"][0]["status"] == "accepted"
    assert [e["event_type"] for e in detail["history"]] == ["request_logged", "quote_issued", "quote_accepted"]
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
    assert api.get("/requests", headers={"X-User-Id": "x", "X-User-Role": "admin"}).status_code == 422


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
    assert response.status_code == 201, response.text
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
