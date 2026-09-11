"""FastAPI application setup."""

from fastapi import FastAPI

from AZFlow.api.v1 import router as v1_router


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    application = FastAPI(title="AZFlow")
    application.include_router(v1_router)
    return application


app = create_app()
