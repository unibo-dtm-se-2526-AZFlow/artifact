"""AZFlow API version 1"""

from fastapi import APIRouter

from AZFlow.api.v1 import health


router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
