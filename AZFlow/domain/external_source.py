"""ExternalSource configuration concept"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalSource:
    """External system connected to AZFlow

    This slice only stores the information needed to identify and use the
    source. Managing sources from the back office is outside its scope.
    """

    id: int
    code: str
    name: str
    connector_type: str
    enabled: bool = True
