"""Small helpers shared by test modules."""
import threading

from app.services.queue_service import QueueService


def joins_within(service: QueueService, seconds: float = 1.0) -> bool:
    """True if service.join() returns within `seconds`.

    join() blocks forever if task_done() was forgotten, so we run it in a
    daemon thread and give up waiting instead of hanging the whole test run.
    """
    waiter = threading.Thread(target=service.join, daemon=True)
    waiter.start()
    waiter.join(timeout=seconds)
    return not waiter.is_alive()