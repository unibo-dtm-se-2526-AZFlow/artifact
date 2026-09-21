"""AZFlow API version 1"""

from fastapi import APIRouter

from AZFlow.api.v1 import check_in, health


router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(check_in.router)
