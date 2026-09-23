"""AZFlow API version 1"""

from fastapi import APIRouter

from AZFlow.api.v1 import (
    calling,
    check_in,
    health,
    queue_view,
    state_management,
    ws_displays,
)


router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(check_in.router)
router.include_router(queue_view.router)
router.include_router(calling.router)
router.include_router(state_management.router)
router.include_router(ws_displays.router)
