"""FastAPI application setup"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from AZFlow.api.composition import (
    wire_calling,
    wire_check_in,
    wire_display_read_model,
    wire_operator_queue_list,
    wire_queue_view,
    wire_state_management,
)
from AZFlow.api.v1 import router as v1_router


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    # Bind the running loop so the call hub can schedule enqueues from the
    # request thread onto the event loop.
    hub = getattr(application.state, "ws_call_hub", None)
    if hub is not None:
        hub.bind_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(title="AZFlow", lifespan=_lifespan)
    application.include_router(v1_router)
    wire_check_in(application)
    wire_queue_view(application)
    wire_operator_queue_list(application)
    wire_calling(application)
    wire_state_management(application)
    wire_display_read_model(application)
    return application


app = create_app()
