import asyncio


class TicketQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()

    async def put(self, ticket_id: int) -> None:
        await self._queue.put(ticket_id)

    async def get(self) -> int:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def put_nowait(self, ticket_id: int) -> None:
        self._queue.put_nowait(ticket_id)