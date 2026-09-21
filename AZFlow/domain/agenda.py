"""Agenda and ExternalAgenda domain concepts"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from AZFlow.domain.external_source import ExternalSource


@dataclass
class Agenda:
    """Local agenda used by AZFlow

    Its name can change without changing the name in the external source.
    """

    id: int
    name: str


@dataclass
class ExternalAgenda:
    """Link between an Agenda and an external source

    The source name can be copied to the local Agenda when it is created.
    The local name can later change independently. The external reference
    format depends on the source.
    """

    agenda: Agenda
    source: ExternalSource
    external_reference: Optional[str] = None
    source_name: Optional[str] = None
