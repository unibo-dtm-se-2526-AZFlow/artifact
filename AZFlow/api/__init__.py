"""FastAPI application setup"""

from fastapi import FastAPI

from AZFlow.api.composition import wire_check_in
from AZFlow.api.v1 import router as v1_router


def create_app() -> FastAPI:
    """Create the FastAPI application"""
    application = FastAPI(title="AZFlow")
    application.include_router(v1_router)
    wire_check_in(application)
    return application


app = create_app()
