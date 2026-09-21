"""TicketMaster domain concept"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TicketMaster:
    """Configuration used to generate public call codes

    The daily counter is managed by the persistence layer and is not stored
    in this object.
    """

    id: int
    prefix: str
