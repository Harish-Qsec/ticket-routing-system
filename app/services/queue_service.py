"""Thin wrapper around queue.Queue. It holds ticket IDs in FIFO order."""
import queue
import time

from app.exceptions import QueueFullError


class QueueService:
    def __init__(self, maxsize: int = 0) -> None:
        # maxsize <= 0 means "unbounded".
        self._queue: queue.Queue[str] = queue.Queue(maxsize=maxsize)

    def enqueue(self, ticket_id: str) -> None:
        """Add an ID to the back of the queue without ever blocking."""
        try:
            self._queue.put_nowait(ticket_id)
        except queue.Full:
            raise QueueFullError(self._queue.maxsize) from None

    def dequeue_nowait(self) -> str | None:
        """Remove and return the front ID, or None if the queue is empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def dequeue(self, timeout: float) -> str | None:
        """Block up to `timeout` seconds for an ID; None if none arrived."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        """Tell the queue that one previously dequeued item is fully handled."""
        self._queue.task_done()

    def join(self, timeout: float | None = None) -> bool:
        """Wait until every enqueued item has been marked done.

        Returns True when all work is done, or False if `timeout` seconds
        ran out first. queue.Queue.join() has no timeout of its own, so this
        uses the queue's condition variable (the usual recipe).
        """
        if timeout is None:
            self._queue.join()
            return True
        deadline = time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def size(self) -> int:
        """Approximate size. Never use it to decide whether get() is safe."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Approximate, like size()."""
        return self._queue.empty()