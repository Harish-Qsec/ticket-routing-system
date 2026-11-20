import logging
import threading


import pytest

from app.exceptions import (
    DuplicateTicketError,
    InvalidStatusTransitionError,
    NoAvailableEngineerError,
)
from app.models.enums import TicketCategory, TicketStatus
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.worker_service import WorkerPool

pytestmark = pytest.mark.concurrency  # every test in this file starts threads


@pytest.fixture
def make_pool(processor, queue_service):
    """Build pools and always stop them, even if the test fails."""
    pools = []

    def _make(num_workers: int = 3) -> WorkerPool:
        pool = WorkerPool(processor, queue_service, num_workers, poll_timeout=0.02)
        pools.append(pool)
        return pool

    yield _make
    for pool in pools:
        pool.stop(drain=False, timeout=2.0)


def add_engineers(engineer_service, make_engineer_data, count):
    for n in range(1, count + 1):
        engineer_service.add_engineer(make_engineer_data(f"E-{n}"))


def add_and_submit_tickets(ticket_service, processor, make_ticket_data, ids):
    for ticket_id in ids:
        ticket_service.create_ticket(make_ticket_data(ticket_id))
        processor.submit(ticket_id)


def assert_every_ticket_assigned_once(ticket_service, expected_count):
    tickets = ticket_service.list_tickets()
    assert len(tickets) == expected_count
    assert all(t.status == TicketStatus.ASSIGNED for t in tickets)
    engineer_ids = [t.assigned_engineer_id for t in tickets]
    assert len(set(engineer_ids)) == expected_count  # nobody assigned twice


# ---------- pool lifecycle ----------


def test_pool_processes_all_queued_tickets(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    add_engineers(engineer_service, make_engineer_data, 10)
    add_and_submit_tickets(
        ticket_service, processor, make_ticket_data, [f"T-{n}" for n in range(10)]
    )
    pool = make_pool(num_workers=3)

    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True

    assert_every_ticket_assigned_once(ticket_service, 10)
    assert pool.is_running is False


def test_stop_on_a_pool_that_never_started_is_safe(make_pool):
    assert make_pool().stop() is True


def test_stop_twice_is_safe(make_pool):
    pool = make_pool()
    pool.start()
    assert pool.stop() is True
    assert pool.stop() is True


def test_start_twice_raises(make_pool):
    pool = make_pool()
    pool.start()
    with pytest.raises(RuntimeError):
        pool.start()


@pytest.mark.parametrize("bad_count", [0, -1])
def test_invalid_worker_count_is_rejected(processor, queue_service, bad_count):
    with pytest.raises(ValueError):
        WorkerPool(processor, queue_service, num_workers=bad_count)


def test_workers_stop_promptly_when_the_queue_is_idle(make_pool):
    pool = make_pool(num_workers=4)
    pool.start()
    assert pool.is_running is True

    assert pool.stop(drain=True, timeout=2.0) is True
    assert pool.is_running is False


# ---------- proof of real concurrency ----------


def test_workers_really_run_concurrently(
    processor, ticket_service, engineer_service, queue_service,
    make_ticket_data, make_engineer_data,
):
    """Three tickets must be inside process_ticket at the SAME moment.

    The barrier only opens when 3 threads are waiting at it together, so a
    single-threaded consumer would time out and fail this test.
    """
    barrier = threading.Barrier(3, timeout=5.0)
    thread_names = []

    class BarrierProcessor(TicketProcessor):
        def process_ticket(self, ticket_id):
            thread_names.append(threading.current_thread().name)
            barrier.wait()
            return super().process_ticket(ticket_id)

    barrier_processor = BarrierProcessor(ticket_service, engineer_service, queue_service)
    add_engineers(engineer_service, make_engineer_data, 3)
    add_and_submit_tickets(
        ticket_service, barrier_processor, make_ticket_data, ["T-1", "T-2", "T-3"]
    )
    pool = WorkerPool(barrier_processor, queue_service, 3, poll_timeout=0.02)

    pool.start()
    try:
        assert pool.stop(drain=True, timeout=5.0) is True
    finally:
        pool.stop(drain=False, timeout=2.0)

    assert len(set(thread_names)) == 3
    assert_every_ticket_assigned_once(ticket_service, 3)


# ---------- no lost or duplicated tickets ----------


def test_many_tickets_many_workers_no_loss_or_duplicates(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    total = 200
    add_engineers(engineer_service, make_engineer_data, total)
    add_and_submit_tickets(
        ticket_service, processor, make_ticket_data, [f"T-{n}" for n in range(total)]
    )
    pool = make_pool(num_workers=8)

    pool.start()
    assert pool.stop(drain=True, timeout=30.0) is True

    assert_every_ticket_assigned_once(ticket_service, total)


def test_concurrent_submission_from_many_producer_threads(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    producers, per_producer = 8, 25
    total = producers * per_producer
    add_engineers(engineer_service, make_engineer_data, total)
    pool = make_pool(num_workers=4)
    pool.start()  # consumers are already running while producers submit

    def produce(producer_number):
        ids = [f"P{producer_number}-{n}" for n in range(per_producer)]
        add_and_submit_tickets(ticket_service, processor, make_ticket_data, ids)

    threads = [threading.Thread(target=produce, args=(p,)) for p in range(producers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert pool.stop(drain=True, timeout=30.0) is True
    assert_every_ticket_assigned_once(ticket_service, total)


def test_concurrent_creates_of_the_same_id_accept_exactly_one(
    ticket_service, make_ticket_data
):
    attempts = 20
    barrier = threading.Barrier(attempts)  # release every thread at once
    outcomes = []

    def attempt():
        barrier.wait()
        try:
            ticket_service.create_ticket(make_ticket_data("T-1"))
            outcomes.append("created")
        except DuplicateTicketError:
            outcomes.append("duplicate")

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert outcomes.count("created") == 1
    assert outcomes.count("duplicate") == attempts - 1
    assert len(ticket_service.list_tickets()) == 1


# ---------- the race condition, now settled by the database ----------


class RacingEngineerService(EngineerService):
    """Forces the race: both threads pick the SAME candidate before either
    one tries to claim it. The barrier lines the two picks up."""

    def __init__(self, session_factory):
        super().__init__(session_factory)
        self._barrier = threading.Barrier(2)
        self._seen = threading.local()

    def _first_available(self, session, category):
        candidate = super()._first_available(session, category)
        if not getattr(self._seen, "waited", False):
            self._seen.waited = True  # only each thread's FIRST pick waits
            self._barrier.wait(timeout=5.0)  # if the partner never comes: fail loudly
        return candidate


def test_two_threads_can_never_get_the_same_engineer(
    session_factory, make_engineer_data
):
    racing = RacingEngineerService(session_factory)
    racing.add_engineer(make_engineer_data("E-1"))
    outcomes = []

    def attempt():
        try:
            engineer = racing.assign_engineer(TicketCategory.NETWORK)
            outcomes.append(engineer.engineer_id)
        except NoAvailableEngineerError:
            outcomes.append("none")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert sorted(outcomes) == ["E-1", "none"]  # exactly one winner


def test_concurrent_submit_of_one_ticket_queues_it_exactly_once(
    processor, ticket_service, queue_service, make_ticket_data
):
    ticket_service.create_ticket(make_ticket_data())
    attempts = 10
    barrier = threading.Barrier(attempts)
    outcomes = []

    def attempt():
        barrier.wait()
        try:
            processor.submit("T-1")
            outcomes.append("queued")
        except InvalidStatusTransitionError:
            outcomes.append("rejected")

    threads = [threading.Thread(target=attempt) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert outcomes.count("queued") == 1
    assert outcomes.count("rejected") == attempts - 1
    assert queue_service.size() == 1


# ---------- worker exception handling ----------


def test_worker_survives_an_unexpected_error_and_keeps_processing(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    original = processor.process_next
    calls = {"count": 0}

    def flaky(timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")  # simulates a bug outside our try/except
        return original(timeout=timeout)

    processor.process_next = flaky
    add_engineers(engineer_service, make_engineer_data, 1)
    add_and_submit_tickets(ticket_service, processor, make_ticket_data, ["T-1"])
    pool = make_pool(num_workers=1)  # one worker, so the first call is its

    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True

    assert calls["count"] >= 2
    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED


def test_worker_survives_a_malformed_result_and_keeps_processing(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    original = processor.process_next
    calls = {"count": 0}

    def malformed_then_real(timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return object()  # no .success attribute: inspecting it raises
        return original(timeout=timeout)

    processor.process_next = malformed_then_real
    add_engineers(engineer_service, make_engineer_data, 1)
    add_and_submit_tickets(ticket_service, processor, make_ticket_data, ["T-1"])
    pool = make_pool(num_workers=1)

    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True

    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED


def test_a_failing_ticket_does_not_stop_the_pool(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    # Only NETWORK engineers exist, so the HARDWARE ticket fails.
    add_engineers(engineer_service, make_engineer_data, 2)
    ticket_service.create_ticket(make_ticket_data("BAD", category=TicketCategory.HARDWARE))
    processor.submit("BAD")
    add_and_submit_tickets(ticket_service, processor, make_ticket_data, ["T-1", "T-2"])
    pool = make_pool(num_workers=2)

    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True

    assert ticket_service.get_ticket("BAD").status == TicketStatus.FAILED
    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED
    assert ticket_service.get_ticket("T-2").status == TicketStatus.ASSIGNED


# ---------- shutdown paths ----------


class StuckProcessor(TicketProcessor):
    """Blocks inside process_ticket until released, to exercise shutdown paths."""

    def __init__(self, *args, entered, release, **kwargs):
        super().__init__(*args, **kwargs)
        self._entered = entered
        self._release = release

    def process_ticket(self, ticket_id):
        self._entered.set()
        self._release.wait(timeout=10.0)
        return super().process_ticket(ticket_id)


def test_stop_reports_failure_while_a_worker_is_stuck_then_succeeds_once_released(
    ticket_service, engineer_service, queue_service,
    make_ticket_data, make_engineer_data,
):
    entered, release = threading.Event(), threading.Event()
    stuck = StuckProcessor(
        ticket_service, engineer_service, queue_service,
        entered=entered, release=release,
    )
    add_engineers(engineer_service, make_engineer_data, 1)
    add_and_submit_tickets(ticket_service, stuck, make_ticket_data, ["T-1"])
    pool = WorkerPool(stuck, queue_service, 1, poll_timeout=0.02)

    pool.start()
    try:
        assert entered.wait(timeout=5.0)  # the worker is now stuck inside T-1
        assert pool.stop(drain=True, timeout=0.3) is False  # cannot drain or join
        assert pool.is_running is True
    finally:
        release.set()

    assert pool.stop(drain=True, timeout=5.0) is True
    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED


def test_stop_without_drain_leaves_waiting_tickets_queued(
    ticket_service, engineer_service, queue_service,
    make_ticket_data, make_engineer_data,
):
    entered, release = threading.Event(), threading.Event()
    stuck = StuckProcessor(
        ticket_service, engineer_service, queue_service,
        entered=entered, release=release,
    )
    add_engineers(engineer_service, make_engineer_data, 2)
    add_and_submit_tickets(ticket_service, stuck, make_ticket_data, ["T-1", "T-2"])
    pool = WorkerPool(stuck, queue_service, 1, poll_timeout=0.02)

    pool.start()
    try:
        assert entered.wait(timeout=5.0)
        assert pool.stop(drain=False, timeout=0.3) is False  # still stuck on T-1
    finally:
        release.set()
    assert pool.stop(drain=False, timeout=5.0) is True

    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED
    assert ticket_service.get_ticket("T-2").status == TicketStatus.QUEUED
    assert queue_service.size() == 1


def test_pool_can_be_started_again_after_a_clean_stop(
    make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    add_engineers(engineer_service, make_engineer_data, 2)
    pool = make_pool(num_workers=2)
    pool.start()
    assert pool.stop() is True

    add_and_submit_tickets(ticket_service, processor, make_ticket_data, ["T-1"])
    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True

    assert ticket_service.get_ticket("T-1").status == TicketStatus.ASSIGNED


@pytest.mark.parametrize("bad_timeout", [0, -0.5])
def test_invalid_poll_timeout_is_rejected(processor, queue_service, bad_timeout):
    with pytest.raises(ValueError):
        WorkerPool(processor, queue_service, poll_timeout=bad_timeout)



def test_a_worker_error_is_logged_with_a_traceback(
    caplog, make_pool, processor, ticket_service, engineer_service,
    make_ticket_data, make_engineer_data,
):
    caplog.set_level(logging.DEBUG, logger="app")
    original = processor.process_next
    calls = {"count": 0}

    def flaky(timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return original(timeout=timeout)

    processor.process_next = flaky
    add_engineers(engineer_service, make_engineer_data, 1)
    add_and_submit_tickets(ticket_service, processor, make_ticket_data, ["T-1"])
    pool = make_pool(num_workers=1)

    pool.start()
    assert pool.stop(drain=True, timeout=5.0) is True  # drain waits until T-1 is done

    errors = [
        r for r in caplog.records
        if r.name == "app.services.worker_service" and r.levelno == logging.ERROR
    ]
    assert errors
    assert errors[0].exc_info is not None