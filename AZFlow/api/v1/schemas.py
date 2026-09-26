"""Shared API v1 schemas."""

from pydantic import BaseModel


class AgendaModel(BaseModel):
    """Agenda representation shared by API v1 responses."""

    id: int
    name: str
