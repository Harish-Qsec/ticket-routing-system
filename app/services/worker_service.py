"""A pool of worker threads that consume the shared FIFO queue.

Producer side: API threads call TicketProcessor.submit().
Consumer side: the threads started here call TicketProcessor.process_next().
"""
import logging
import threading
import time

from app.services.processing_service import TicketProcessor
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(
        self,
        processor: TicketProcessor,
        queue_service: QueueService,
        num_workers: int = 3,
        poll_timeout: float = 0.2,
    ) -> None:
        if num_workers < 1:
            raise ValueError("num_workers must be at least 1")
        if poll_timeout <= 0:
            raise ValueError("poll_timeout must be positive")
        self._processor = processor
        self._queue = queue_service
        self._num_workers = num_workers
        self._poll_timeout = poll_timeout
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("WorkerPool is already started")
        self._stop_event.clear()
        for number in range(1, self._num_workers + 1):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"worker-{number}",
                daemon=True,  # safety net so a forgotten stop() can't hang exit
            )
            self._threads.append(thread)
            thread.start()

    def stop(self, drain: bool = True, timeout: float = 10.0) -> bool:
        """Shut the workers down. Returns True if everything stopped cleanly.

        drain=True  : first wait until every queued ticket has been processed.
        drain=False : stop after the tickets currently in progress; anything
                      still queued stays QUEUED (Phase 5 re-enqueues it).
        """
        deadline = time.monotonic() + timeout
        drained = True
        if drain and self._threads:
            drained = self._queue.join(timeout=timeout)
            if not drained:
                logger.warning("Shutdown timed out while draining the queue")
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._threads = [t for t in self._threads if t.is_alive()]
        if self._threads:
            logger.warning("%d worker(s) did not stop in time", len(self._threads))
        return drained and not self._threads

    def _worker_loop(self) -> None:
        name = threading.current_thread().name
        logger.info("%s started", name)
        while not self._stop_event.is_set():
            try:
                # Blocks up to poll_timeout, then returns None so we can
                # re-check the stop flag.
                result = self._processor.process_next(timeout=self._poll_timeout)
            except Exception:
                logger.exception("%s hit an unexpected error; continuing", name)
                self._stop_event.wait(0.05)  # brief back-off, no hot loop
                continue
            if result is not None and not result.success:
                logger.warning(
                    "%s: ticket %s failed: %s", name, result.ticket_id, result.error
                )
        logger.info("%s stopped", name)