import threading
import pytest

from app.exceptions import QueueFullError
from app.services.queue_service import QueueService
from tests.helpers import joins_within


def test_dequeue_returns_items_in_fifo_order(queue_service):
    for ticket_id in ("T-1", "T-2", "T-3"):
        queue_service.enqueue(ticket_id)

    taken = [queue_service.dequeue_nowait() for _ in range(3)]
    assert taken == ["T-1", "T-2", "T-3"]


def test_dequeue_nowait_on_empty_queue_returns_none(queue_service):
    assert queue_service.dequeue_nowait() is None


def test_dequeue_with_timeout_on_empty_queue_returns_none(queue_service):
    assert queue_service.dequeue(timeout=0.01) is None


def test_size_and_is_empty(queue_service):
    assert queue_service.is_empty()

    queue_service.enqueue("T-1")
    assert queue_service.size() == 1
    assert not queue_service.is_empty()

    queue_service.dequeue_nowait()
    assert queue_service.is_empty()


def test_bounded_queue_raises_when_full():
    bounded = QueueService(maxsize=1)
    bounded.enqueue("T-1")

    with pytest.raises(QueueFullError):
        bounded.enqueue("T-2")

    assert bounded.size() == 1


def test_join_returns_once_every_item_is_marked_done(queue_service):
    queue_service.enqueue("T-1")
    queue_service.dequeue_nowait()
    queue_service.task_done()

    assert joins_within(queue_service)


def test_join_keeps_waiting_while_work_is_unfinished(queue_service):
    queue_service.enqueue("T-1")
    queue_service.dequeue_nowait()  # taken, but task_done() not called yet

    assert not joins_within(queue_service, seconds=0.1)

    queue_service.task_done()  # releases the thread that is still waiting


def test_task_done_more_often_than_items_raises(queue_service):
    with pytest.raises(ValueError):
        queue_service.task_done()



def test_join_with_timeout_returns_false_while_work_is_unfinished(queue_service):
    queue_service.enqueue("T-1")
    queue_service.dequeue_nowait()  # taken, task_done() not called

    assert queue_service.join(timeout=0.05) is False

    queue_service.task_done()
    assert queue_service.join(timeout=0.05) is True



def test_dequeue_with_timeout_returns_an_item_that_is_already_waiting(queue_service):
    queue_service.enqueue("T-1")

    assert queue_service.dequeue(timeout=1.0) == "T-1"


def test_a_blocked_dequeue_wakes_up_when_an_item_arrives(queue_service):
    timer = threading.Timer(0.05, queue_service.enqueue, args=("T-1",))
    timer.start()
    try:
        assert queue_service.dequeue(timeout=5.0) == "T-1"
    finally:
        timer.cancel()