# Task 1 (A2 Scenario 2): finding drivers for a job and allocating or reallocating it
from datetime import timedelta
from decimal import Decimal

import pytest

from swe.app import (
    AcceptQuote,
    AllocateJob,
    CreateDeliveryJob,
    DeclareSlot,
    DeliveryManagementSystem,
    IssueQuote,
    LogRequest,
    ReallocateJob,
)
from swe.domain.job import DeliveryJob, JobStateName
from swe.domain.shared import DomainError
from swe.domain.shared.ids import now
from swe.domain.user import Customer, DeliveryStaff, StaffMember
from swe.repo import ConflictError

T = now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
PICKUP = (T + timedelta(hours=1), T + timedelta(hours=3))


@pytest.fixture
def dms(repo):
    ticks = iter(range(1000))
    dms = DeliveryManagementSystem(repo, clock=lambda: now() + timedelta(seconds=next(ticks)))
    for user in [
        Customer(user_id="cust-1", name="Sam", phone="0400000000"),
        StaffMember(user_id="staff-1", name="Alex", phone="0400000001"),
        DeliveryStaff(user_id="driver-1", name="Lee", phone="0400000002"),
        DeliveryStaff(user_id="driver-2", name="Kim", phone="0400000003"),
        DeliveryStaff(user_id="driver-3", name="Jo", phone="0400000004"),
    ]:
        dms.users.add(user)
    return dms


def free(dms, driver, start=0, end=8):
    dms.declare_slot(
        DeclareSlot(delivery_staff_id=driver, window=(T + timedelta(hours=start), T + timedelta(hours=end)), by=driver)
    )


# an accepted quote turned into an unallocated job, as the handler would
def new_job(dms) -> DeliveryJob:
    request = dms.log_request(
        LogRequest(
            customer_id="cust-1",
            contact_name="Sam",
            contact_phone="0400000000",
            parcels=[{"size": "small", "weight_kg": "2"}],
            pickup_address={"street": "1 A St", "suburb": "Hawthorn", "postcode": "3122"},
            dropoff_address={"street": "2 B St", "suburb": "Kew", "postcode": "3101"},
        )
    )
    quote = dms.issue_quote(
        IssueQuote(
            request_id=request.request_id,
            staff_id="staff-1",
            price=Decimal("50"),
            eta_pickup=PICKUP,
            eta_dropoff=(PICKUP[1], PICKUP[1] + timedelta(hours=2)),
        )
    )
    accepted = dms.accept_quote(
        AcceptQuote(request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1")
    )
    return dms.create_delivery_job(
        CreateDeliveryJob(
            job_id=accepted.job_id, request_id=request.request_id, quote_id=quote.quote_id, customer_id="cust-1"
        )
    )


def allocate(dms, job, driver):
    return dms.allocate_job(AllocateJob(job_id=job.job_id, delivery_staff_id=driver, by="staff-1"))


def test_allocation_moves_the_job_to_allocated_and_records_who(dms, repo):
    free(dms, "driver-1")
    job = new_job(dms)
    allocation = allocate(dms, job, "driver-1")

    saved = repo.get_job(job.job_id)
    assert (saved.state, saved.delivery_staff_id, saved.allocation_id) == (
        JobStateName.ALLOCATED,
        "driver-1",
        allocation.id,
    )
    assert repo.list_allocations(job.job_id) == [allocation]
    assert (allocation.created_by, allocation.replaces) == ("staff-1", None)
    allocated = repo.get_history(job.request_id)[-1]
    assert (allocated.event_type, allocated.delivery_staff_id, allocated.created_by) == (
        "job_allocated",
        "driver-1",
        "staff-1",
    )
    assert [j.job_id for j in repo.list_driver_jobs("driver-1")] == [job.job_id]


def test_candidates_cover_the_pickup_window_and_are_ranked_by_load(dms):
    free(dms, "driver-1")
    free(dms, "driver-2")
    free(dms, "driver-3", start=2, end=8)  # starts after the pickup window does
    busy = new_job(dms)
    allocate(dms, busy, "driver-1")

    candidates = dms.job_candidates(new_job(dms).job_id)
    assert [(c.driver.user_id, c.load) for c in candidates] == [("driver-2", 0), ("driver-1", 1)]


def test_no_candidates_means_renegotiating(dms):
    assert dms.job_candidates(new_job(dms).job_id) == []  # nobody has declared a slot (Task 1 2a)


def test_unavailable_driver_is_refused(dms, repo):
    free(dms, "driver-1", start=2, end=8)
    job = new_job(dms)
    with pytest.raises(DomainError, match="isn't available"):
        allocate(dms, job, "driver-1")
    with pytest.raises(DomainError, match="isn't available"):
        allocate(dms, job, "staff-1")  # not a driver
    assert repo.get_job(job.job_id).state is JobStateName.UNALLOCATED
    assert repo.list_allocations(job.job_id) == []


def test_allocating_an_allocated_job_says_who_has_it(dms, repo):
    free(dms, "driver-1")
    free(dms, "driver-2")
    job = new_job(dms)
    allocate(dms, job, "driver-1")
    with pytest.raises(DomainError, match="already allocated to driver-1"):
        allocate(dms, job, "driver-2")
    assert len(repo.list_allocations(job.job_id)) == 1


# both staff loaded the unallocated job before either saved (variant 3a)
def test_concurrent_allocation_conflicts(dms, repo, monkeypatch):
    free(dms, "driver-1")
    free(dms, "driver-2")
    job = new_job(dms)
    stale = repo.get_job(job.job_id)
    allocate(dms, job, "driver-1")
    monkeypatch.setattr(repo, "get_job", lambda job_id: stale)
    with pytest.raises(ConflictError):
        allocate(dms, job, "driver-2")
    monkeypatch.undo()
    assert repo.get_job(job.job_id).delivery_staff_id == "driver-1"
    assert len(repo.list_allocations(job.job_id)) == 1


def test_reallocation_keeps_the_trail(dms, repo):
    free(dms, "driver-1")
    free(dms, "driver-2")
    job = new_job(dms)
    first = allocate(dms, job, "driver-1")
    second = dms.reallocate_job(
        ReallocateJob(job_id=job.job_id, delivery_staff_id="driver-2", reason="driver-1 is sick", by="staff-1")
    )

    saved = repo.get_job(job.job_id)
    assert (saved.state, saved.delivery_staff_id) == (JobStateName.ALLOCATED, "driver-2")
    assert repo.list_allocations(job.job_id) == [first, second]
    assert (second.replaces, second.reason) == (first.id, "driver-1 is sick")
    assert repo.list_driver_jobs("driver-1") == []
    event = repo.get_history(job.request_id)[-1]
    assert (event.previous_delivery_staff_id, event.reason) == ("driver-1", "driver-1 is sick")


def test_reallocation_is_refused_when_it_cant_apply(dms):
    free(dms, "driver-1")
    job = new_job(dms)
    reallocate = lambda driver: dms.reallocate_job(  # noqa: E731
        ReallocateJob(job_id=job.job_id, delivery_staff_id=driver, reason="cover", by="staff-1")
    )
    with pytest.raises(DomainError):
        reallocate("driver-1")  # nothing to reallocate yet
    allocate(dms, job, "driver-1")
    with pytest.raises(DomainError, match="already allocated to driver-1"):
        reallocate("driver-1")
    with pytest.raises(ValueError):
        ReallocateJob(job_id=job.job_id, delivery_staff_id="driver-2", reason="", by="staff-1")


# the design's rule: reallocating doesn't change the job's stage (§5.2.1)
def test_reallocating_in_transit_stays_in_transit():
    job = DeliveryJob(request_id="r", quote_id="q", customer_id="c", state=JobStateName.IN_TRANSIT)
    job.allocation_id, job.delivery_staff_id = "a-1", "driver-1"
    allocation, _ = job.reallocate("driver-2", reason="swap", by="staff-1")
    assert job.state is JobStateName.IN_TRANSIT
    assert allocation.replaces == "a-1"
