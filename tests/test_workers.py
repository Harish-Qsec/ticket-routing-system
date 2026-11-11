import threading

import pytest

from app.exceptions import DuplicateTicketError, NoAvailableEngineerError
from app.models.enums import TicketCategory, TicketStatus
from app.services.processing_service import TicketProcessor
from app.services.worker_service import WorkerPool


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
    barrier = threading.Barrier(3, timeout=2.0)
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
    assert pool.stop(drain=True, timeout=10.0) is True

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

    assert pool.stop(drain=True, timeout=10.0) is True
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


# ---------- the race condition, reproduced on purpose ----------


class SlowCheckEngineer:
    """Test double that forces the race: both threads READ is_available=True
    before either one WRITES False. The barrier lines the two reads up."""

    def __init__(self, engineer_id, skills):
        self.engineer_id = engineer_id
        self.skills = skills
        self._available = True
        self._barrier = threading.Barrier(2)

    @property
    def is_available(self):
        value = self._available
        try:
            self._barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass  # the other thread is locked out, so it can never arrive
        return value

    @is_available.setter
    def is_available(self, new_value):
        self._available = new_value


def test_two_threads_can_never_get_the_same_engineer(engineer_service):
    # Reaching into the private dict is acceptable in a test that needs a double.
    engineer_service._engineers["E-1"] = SlowCheckEngineer(
        "E-1", {TicketCategory.NETWORK}
    )
    outcomes = []

    def attempt():
        try:
            engineer = engineer_service.assign_engineer(TicketCategory.NETWORK)
            outcomes.append(engineer.engineer_id)
        except NoAvailableEngineerError:
            outcomes.append("none")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert sorted(outcomes) == ["E-1", "none"]  # exactly one winner


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