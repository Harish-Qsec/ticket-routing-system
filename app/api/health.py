"""A tiny health endpoint for humans, scripts and load balancers."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import ContainerDep

router = APIRouter(tags=["health"])


class HealthRead(BaseModel):
    status: str
    workers_running: bool
    queue_size: int


@router.get("/health", response_model=HealthRead)
def health(container: ContainerDep):
    return HealthRead(
        status="ok",
        workers_running=container.pool.is_running,
        queue_size=container.queue.size(),
    )