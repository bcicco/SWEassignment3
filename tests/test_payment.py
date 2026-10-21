# Task 7 and closure (A2 Scenario 7.4): recording payments, flagging variances, correcting
# them with adjustments, closing the job and the daily totals
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_execution_workflow import attempt, flow, post  # noqa: F401  flow is a fixture

from swe.domain.job import Payment, PaymentAdjustment, Settlement
from swe.domain.shared import DomainError
from swe.events import handlers
from swe.repo.schemas.job import PAYMENT, SETTLEMENT

DAY = "2026-10-20"  # the flow's clock, in Melbourne


@pytest.fixture
def delivered(flow):  # noqa: F811
    for kind in ("pickup", "delivery"):
        response, _ = attempt(flow, kind=kind)
        assert response.status_code == 200, response.text
    return flow


# each action a minute after the last, so the history reads back in order
def tick(c):
    c.clock[0] += timedelta(minutes=1)


def pay(c, amount="50", method="cash", outcome="collected", reason=None, user="driver-1", payment_id=None):
    tick(c)
    body = {"payment_id": payment_id or str(uuid4()), "outcome": outcome, "method": method, "amount": amount}
    if reason is not None:
        body["reason"] = reason
    return post(c, f"/jobs/{c.job_id}/payments", body, user=user)


def adjust(c, payment_id, amount="5", method="card", reference="APPROVAL-7731", reason="Balance paid by card", **kw):
    tick(c)
    body = {
        "adjustment_id": str(uuid4()),
        "amount": amount,
        "method": method,
        "provider_reference": reference,
        "reason": reason,
    }
    return post(c, f"/jobs/{c.job_id}/payments/{payment_id}/adjustments", body, user=kw.get("user", "staff-1"))


def payments(c, user="staff-1"):
    response = c.client.get(f"/jobs/{c.job_id}/payments", headers={"X-User-Id": user})
    assert response.status_code == 200, response.text
    return response.json()


def close(c, user="staff-1"):
    tick(c)
    return post(c, f"/jobs/{c.job_id}/close", user=user)


def collections(c, staff_id, user="staff-1"):
    return c.client.get(f"/collections?day={DAY}&staff_id={staff_id}", headers={"X-User-Id": user})


# A2 Scenario 7.4 main path: $45 cash with a reason, closure refused, +$5 card balance, closed
def test_shortfall_is_flagged_then_balanced_and_the_job_closes(delivered):
    c = delivered
    assert Decimal(payments(c)["settlement"]["outstanding"]) == 50

    response = pay(c, amount="45", reason="Customer short $5")
    assert response.status_code == 201, response.text
    payment = response.json()
    assert Decimal(payment["variance"]) == -5
    assert Decimal(payment["amount_due"]) == 50
    detail = payments(c)
    assert Decimal(detail["settlement"]["outstanding"]) == 5
    assert detail["settlement"]["resolved"] is False

    response = close(c)
    assert response.status_code == 400
    assert "payment must be resolved" in response.json()["detail"]

    response = adjust(c, payment["id"])
    assert response.status_code == 201, response.text
    detail = payments(c)
    assert detail["settlement"]["resolved"] is True
    assert [Decimal(p["amount"]) for p in detail["payments"]] == [45]  # the $45 is never changed (QA3.5)

    response = close(c)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "closed"
    history = [
        e["event_type"]
        for e in c.client.get(
            f"/requests/{c.repo.get_job(c.job_id).request_id}", headers={"X-User-Id": "staff-1"}
        ).json()["history"]
    ]
    assert history[-3:] == ["payment_recorded", "payment_adjusted", "job_closed"]

    # QA3.6: the driver handed in $45 cash; the $5 card balance is the office staff member's
    driver = collections(c, "driver-1").json()
    assert (Decimal(driver["cash"]), Decimal(driver["card"])) == (45, 0)
    office = collections(c, "staff-1").json()
    assert (Decimal(office["cash"]), Decimal(office["card"])) == (0, 5)
    assert len(office["adjustments"]) == 1


def test_full_payment_resolves_without_variance(delivered):
    response = pay(delivered)
    assert response.status_code == 201, response.text
    assert Decimal(response.json()["variance"]) == 0
    assert payments(delivered)["settlement"]["resolved"] is True
    assert close(delivered).status_code == 200


# Task 7 3a: a shortfall without a reason is refused and nothing is recorded
def test_shortfall_needs_a_reason(delivered):
    response = pay(delivered, amount="45")
    assert response.status_code == 400
    assert "reason is required" in response.json()["detail"]
    detail = payments(delivered)
    assert detail["payments"] == []
    assert detail["settlement"]["revision"] == 0


@pytest.mark.parametrize(
    "body, message",
    [
        ({"amount": "0"}, "amount above zero"),
        ({"amount": "45.001", "reason": "short"}, "decimal places"),
        ({"amount": "-5"}, "greater than or equal to 0"),
        ({"method": None}, "needs its method"),
        ({"outcome": "declined", "method": "cash", "amount": "0", "reason": "no"}, "only a card payment"),
        ({"outcome": "declined", "method": "card", "amount": "0"}, "needs a reason"),
        ({"outcome": "refused", "method": None, "amount": "10", "reason": "no"}, "collects nothing"),
    ],
)
def test_invalid_payments_are_refused(delivered, body, message):
    response = pay(delivered, **body)
    assert response.status_code in (400, 422), response.text
    assert message in str(response.json()["detail"])
    assert payments(delivered)["payments"] == []


# Task 7 2a: the declined card is kept, then the driver falls back to cash
def test_declined_card_is_recorded_before_the_cash_fallback(delivered):
    response = pay(delivered, outcome="declined", method="card", amount="0", reason="Card declined by device")
    assert response.status_code == 201, response.text
    assert Decimal(payments(delivered)["settlement"]["outstanding"]) == 50
    assert pay(delivered).status_code == 201
    detail = payments(delivered)
    assert [p["outcome"] for p in detail["payments"]] == ["declined", "collected"]
    assert detail["settlement"]["resolved"] is True


# Task 7 3b: the job is flagged, not closed as delivered with no payment
def test_refused_payment_keeps_the_job_open(delivered):
    response = pay(delivered, outcome="refused", method=None, amount="0", reason="Customer disputes the price")
    assert response.status_code == 201, response.text
    assert close(delivered).status_code == 400
    assert payments(delivered)["settlement"]["resolved"] is False


def test_nothing_more_is_collected_once_resolved(delivered):
    assert pay(delivered).status_code == 201
    response = pay(delivered, amount="10")
    assert response.status_code == 400
    assert "already resolved" in response.json()["detail"]


# A2 7.4 alternatives for the adjustment: a reason, and a reference for card, are required;
# a card number is never accepted as one (QA3.8)
@pytest.mark.parametrize(
    "changes, message",
    [
        ({"reference": None}, "device's reference"),
        ({"reference": "4111 1111 1111 1111"}, "never a card number"),
        ({"reason": "  "}, "at least 1 character"),
        ({"amount": "0"}, "non-zero amount"),
        ({"amount": "-50"}, "below zero"),
    ],
)
def test_invalid_adjustments_are_refused(delivered, changes, message):
    payment = pay(delivered, amount="45", reason="Customer short $5").json()
    response = adjust(delivered, payment["id"], **changes)
    assert response.status_code in (400, 422), response.text
    assert message in str(response.json()["detail"])
    assert payments(delivered)["adjustments"] == []


def test_cash_adjustment_needs_no_reference(delivered):
    payment = pay(delivered, amount="45", reason="Customer short $5").json()
    response = adjust(delivered, payment["id"], method="cash", reference=None, reason="Customer dropped off $5")
    assert response.status_code == 201, response.text


# Task 7 4a: an error found after the payment resolved is corrected, not edited
def test_correction_after_resolution(delivered):
    payment = pay(delivered).json()
    response = adjust(
        delivered, payment["id"], amount="-5", method="cash", reference=None, reason="Recorded $5 too much"
    )
    assert response.status_code == 201, response.text
    assert Decimal(payments(delivered)["settlement"]["outstanding"]) == 5
    assert close(delivered).status_code == 400


@pytest.mark.parametrize("user, status", [("cust-1", 403), ("driver-2", 403), ("staff-1", 403)])
def test_only_the_allocated_driver_records_payment(delivered, user, status):
    assert pay(delivered, user=user).status_code == status


def test_only_office_staff_adjust_and_close(delivered):
    payment = pay(delivered, amount="45", reason="Customer short $5").json()
    assert adjust(delivered, payment["id"], user="driver-1").status_code == 403
    assert adjust(delivered, payment["id"], user="cust-1").status_code == 403
    assert close(delivered, user="driver-1").status_code == 403


def test_customers_see_only_their_own_payments(delivered):
    pay(delivered)
    assert len(payments(delivered, user="cust-1")["payments"]) == 1
    response = delivered.client.get(f"/jobs/{delivered.job_id}/payments", headers={"X-User-Id": "cust-2"})
    assert response.status_code == 403


def test_collection_totals_are_restricted(delivered):
    assert collections(delivered, "driver-1", user="driver-1").status_code == 200
    assert collections(delivered, "driver-2", user="driver-1").status_code == 403
    assert collections(delivered, "driver-1", user="cust-1").status_code == 403


# A2 §7.3 deferred duplicate submissions: a retry with the same id is the same payment
def test_retried_payment_is_recorded_once(delivered):
    payment_id = str(uuid4())
    first = pay(delivered, amount="45", reason="Customer short $5", payment_id=payment_id)
    retry = pay(delivered, amount="45", reason="Customer short $5", payment_id=payment_id)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert len(payments(delivered)["payments"]) == 1
    response = pay(delivered, amount="40", reason="Customer short $10", payment_id=payment_id)
    assert response.status_code == 409


# two payments taken against the same balance at once can't both be saved
def test_concurrent_payments_conflict(delivered, monkeypatch):
    system = delivered.client.app.state.dms
    stale = system.settlement(system.repo.get_job(delivered.job_id))
    assert pay(delivered, amount="20", reason="Part payment").status_code == 201
    monkeypatch.setattr(system, "settlement", lambda job: stale.model_copy())
    response = pay(delivered, amount="30", reason="Part payment")
    assert response.status_code == 409
    assert len(payments(delivered)["payments"]) == 1


# a payment at pickup is allowed (A2 Allocated card) but isn't evidence of delivery
def test_paid_job_closes_only_once_delivered(flow):  # noqa: F811
    response, _ = attempt(flow)
    assert response.status_code == 200, response.text
    assert pay(flow).status_code == 201
    response = close(flow)
    assert response.status_code == 400
    assert "in transit" in response.json()["detail"]


def test_closed_job_refuses_further_money(delivered):
    payment = pay(delivered).json()
    assert close(delivered).status_code == 200
    response = adjust(delivered, payment["id"], method="cash", reference=None)
    assert response.status_code == 400
    assert "closed" in response.json()["detail"]
    assert close(delivered).status_code == 400


def test_payment_events_reach_their_handlers(delivered, caplog):
    payment = pay(delivered, amount="45", reason="Customer short $5").json()
    adjust(delivered, payment["id"])
    close(delivered)
    history = delivered.repo.get_history(delivered.repo.get_job(delivered.job_id).request_id)
    caplog.set_level("INFO")
    for event in history[-3:]:
        detail = {"detail": event.model_dump(mode="json")}
        handler = handlers.notify_customer if event.event_type == "job_closed" else handlers.notify_office_staff
        handler(detail)
    assert "$5 outstanding" in caplog.text
    assert "paid in full" in caplog.text
    assert "is complete" in caplog.text


def test_payment_and_settlement_round_trip():
    payment = Payment(
        id="p1",
        job_id="j1",
        quote_id="q1",
        outcome="collected",
        method="cash",
        amount_due=Decimal("50"),
        amount=Decimal("45.50"),
        reason="short",
        created_by="driver-1",
    )
    assert PAYMENT.from_item(PAYMENT.to_item(payment)) == payment
    settlement = Settlement(job_id="j1", amount_due=Decimal("50"), net_collected=Decimal("45.50"), revision=1)
    assert SETTLEMENT.from_item(SETTLEMENT.to_item(settlement)) == settlement


def test_settlement_and_records_are_append_only():
    settlement = Settlement(job_id="j1", amount_due=Decimal("50"))
    with pytest.raises(ValueError):
        settlement.amount_due = Decimal("10")
    adjustment = PaymentAdjustment(
        job_id="j1", payment_id="p1", amount=Decimal("5"), method="cash", reason="balance", created_by="staff-1"
    )
    with pytest.raises(ValueError):
        adjustment.amount = Decimal("6")
    settlement.apply_adjustment(adjustment)
    settlement.apply_adjustment(adjustment.model_copy(update={"amount": Decimal("45")}))
    with pytest.raises(DomainError, match="already resolved"):
        settlement.due()
