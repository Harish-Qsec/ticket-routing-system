"""Application entry point: builds the FastAPI app and owns startup/shutdown."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import engineers, health, tickets
from app.api.errors import register_error_handlers
from app.config import Settings, load_settings
from app.container import build_container


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- startup ----
        container = build_container(settings)
        app.state.container = container
        container.processor.restore_queue()  # rebuild the queue from the database
        container.pool.start()
        try:
            yield
        finally:
            # ---- shutdown: finish queued work, then close the database ----
            await asyncio.to_thread(container.pool.stop, True, 10.0)
            container.engine.dispose()

    app = FastAPI(
        title="Centralized IT Ticket Routing System",
        version="1.0.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(tickets.router)
    app.include_router(engineers.router)
    return app


app = create_app()