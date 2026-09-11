import logging


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("AZFlow")


def main() -> None:
    """Start the AZFlow application."""
    import uvicorn

    from AZFlow.infrastructure.config import load_settings

    settings = load_settings()
    logger.info("AZFlow starting on %s:%s", settings.api_host, settings.api_port)

    uvicorn.run(
        "AZFlow.api:app",
        host=settings.api_host,
        port=settings.api_port,
    )
