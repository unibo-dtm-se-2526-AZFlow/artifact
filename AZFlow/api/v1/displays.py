"""Display read-model dependency

This module exposes only the dependency used to read display views. It adds no
routes in this slice; display views are read through the application interface.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from AZFlow.application.ports.display_read_model import DisplayReadModel


def get_display_read_model() -> DisplayReadModel:
    """Provide the DisplayReadModel used to read display views

    The application setup and tests replace this dependency.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="display read model is not configured",
    )
