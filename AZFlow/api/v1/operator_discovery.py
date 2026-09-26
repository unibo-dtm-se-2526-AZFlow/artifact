"""Operator client discovery endpoints."""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from AZFlow.application.ports.operator_discovery_read_model import (
    OperatorDiscoveryReadModel,
)

from AZFlow.api.v1.schemas import AgendaModel


router = APIRouter()


class OperatorRoomModel(BaseModel):
    """Room exposed to operator clients."""

    id: int
    room_reference: str
    label: str



class OperatorQueueModel(BaseModel):
    """Queue exposed to operator clients."""

    id: int
    status: str
    policy: str
    agendas: List[AgendaModel]


def get_operator_discovery_read_model() -> OperatorDiscoveryReadModel:
    """Dependency replaced by API composition or tests."""
    raise RuntimeError("operator discovery read model is not configured")


@router.get("/rooms", response_model=List[OperatorRoomModel])
def list_rooms(
    read_model: OperatorDiscoveryReadModel = Depends(
        get_operator_discovery_read_model
    ),
) -> List[OperatorRoomModel]:
    """List Rooms available to operator clients."""
    return [
        OperatorRoomModel(
            id=room.id,
            room_reference=room.room_reference,
            label=room.label,
        )
        for room in read_model.list_rooms()
    ]


@router.get("/queues", response_model=List[OperatorQueueModel])
def list_queues(
    read_model: OperatorDiscoveryReadModel = Depends(
        get_operator_discovery_read_model
    ),
) -> List[OperatorQueueModel]:
    """List Queues available to operator clients."""
    return [
        OperatorQueueModel(
            id=queue.id,
            status=queue.status.value,
            policy=queue.policy.value,
            agendas=[
                AgendaModel(id=agenda.id, name=agenda.name)
                for agenda in queue.agendas
            ],
        )
        for queue in read_model.list_queues()
    ]
