"""Engineer endpoints."""
from fastapi import APIRouter, Response, status

from app.api.dependencies import EngineerServiceDep
from app.schemas.engineer import EngineerCreate, EngineerRead

router = APIRouter(prefix="/engineers", tags=["engineers"])


@router.get("", response_model=list[EngineerRead])
def list_engineers(engineers: EngineerServiceDep):
    return engineers.list_engineers()


@router.post("", response_model=EngineerRead, status_code=status.HTTP_201_CREATED)
def add_engineer(data: EngineerCreate, response: Response, engineers: EngineerServiceDep):
    engineer = engineers.add_engineer(data)
    response.headers["Location"] = "/engineers"
    return engineer