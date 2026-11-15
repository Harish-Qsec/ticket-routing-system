"""FastAPI dependencies: how endpoints get hold of the services."""
from typing import Annotated

from fastapi import Depends, Request

from app.container import AppContainer
from app.services.engineer_service import EngineerService
from app.services.processing_service import TicketProcessor
from app.services.ticket_service import TicketService


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def get_ticket_service(container: ContainerDep) -> TicketService:
    return container.tickets


def get_engineer_service(container: ContainerDep) -> EngineerService:
    return container.engineers


def get_processor(container: ContainerDep) -> TicketProcessor:
    return container.processor


TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]
EngineerServiceDep = Annotated[EngineerService, Depends(get_engineer_service)]
ProcessorDep = Annotated[TicketProcessor, Depends(get_processor)]