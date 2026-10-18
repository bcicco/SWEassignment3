# the lifecycle rules in §5.2.1's table
import pytest

from swe.domain.job import (
    Allocated,
    Closed,
    Delivered,
    DeliveryJob,
    InTransit,
    JobState,
    JobStateName,
    OnHold,
    Unallocated,
)
from swe.domain.shared import DomainError

OK = dict(payment_resolved=True, issue_open=False)


@pytest.mark.parametrize(
    ("state", "action", "successor"),
    [
        (Unallocated(), lambda s: s.allocate(), Allocated()),
        (Allocated(), lambda s: s.record_pickup(succeeded=True), InTransit()),
        (Allocated(), lambda s: s.record_pickup(succeeded=False), OnHold()),
        (InTransit(), lambda s: s.record_delivery(succeeded=False), OnHold()),
        (InTransit(), lambda s: s.record_delivery(succeeded=True), Delivered()),
        (OnHold(), lambda s: s.resume(issue_addressed=True, parcels_with_driver=False), Allocated()),
        (OnHold(), lambda s: s.resume(issue_addressed=True, parcels_with_driver=True), InTransit()),
        (Delivered(), lambda s: s.close(**OK), Closed()),
    ],
)
def test_permitted_transitions(state, action, successor):
    assert action(state) == successor


# reallocating keeps the stage, so an OnHold job stays on hold (§5.2.1)
@pytest.mark.parametrize("state", [Allocated(), InTransit(), OnHold()])
def test_reallocation_keeps_the_stage(state):
    assert state.reallocate() == state


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (Allocated(), lambda s: s.allocate()),  # allocated twice (Task 1 3a)
        (Unallocated(), lambda s: s.record_pickup(succeeded=True)),
        (Unallocated(), lambda s: s.reallocate()),
        (Allocated(), lambda s: s.record_delivery(succeeded=True)),  # before collection
        (InTransit(), lambda s: s.close(**OK)),  # before handover (Task 4 5a)
        (OnHold(), lambda s: s.record_delivery(succeeded=True)),
        (OnHold(), lambda s: s.resume(issue_addressed=False, parcels_with_driver=True)),
        (Delivered(), lambda s: s.record_delivery(succeeded=True)),
        (Delivered(), lambda s: s.close(payment_resolved=False, issue_open=False)),  # Task 7 3b
        (Delivered(), lambda s: s.close(payment_resolved=True, issue_open=True)),
        (Unallocated(), lambda s: s.record_payment()),
        (Closed(), lambda s: s.allocate()),
        (Closed(), lambda s: s.record_payment()),
    ],
)
def test_refused_actions(state, action):
    with pytest.raises(DomainError):
        action(state)


def test_every_stored_name_has_a_state():
    for name in JobStateName:
        assert JobState.for_name(name).name is name


def test_job_moves_through_its_state():
    job = DeliveryJob(request_id="r", quote_id="q", customer_id="c")
    assert job.current_state == Unallocated()
    job.enter(job.current_state.allocate())
    assert (job.state, job.current_state) == (JobStateName.ALLOCATED, Allocated())
    with pytest.raises(DomainError):
        job.enter(job.current_state.allocate())
    assert job.state is JobStateName.ALLOCATED  # a refusal leaves the job unchanged
