"""Application entry point: builds the FastAPI app and owns startup/shutdown."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.engine import make_url

from app.api import engineers, health, tickets
from app.api.errors import register_error_handlers
from app.api.middleware import install_request_logging
from app.config import Settings, load_settings
from app.container import build_container
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ---- startup ----
        container = build_container(settings)
        app.state.container = container
        # hide_password: a database URL can contain credentials.
        database = make_url(settings.database_url).render_as_string(hide_password=True)
        logger.info(
            "starting: %d worker(s), database %s", settings.num_workers, database
        )
        container.processor.restore_queue()  # rebuild the queue from the database
        container.pool.start()
        try:
            yield
        finally:
            # ---- shutdown: finish queued work, then close the database ----
            logger.info("shutting down")
            clean = await asyncio.to_thread(container.pool.stop, True, 10.0)
            if not clean:
                logger.warning("workers did not stop cleanly; unfinished tickets stay QUEUED")
            container.engine.dispose()
            logger.info("stopped")

    app = FastAPI(
        title="Centralized IT Ticket Routing System",
        version="1.0.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    install_request_logging(app)
    app.include_router(health.router)
    app.include_router(tickets.router)
    app.include_router(engineers.router)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    return app


app = create_app()