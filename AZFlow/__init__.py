import logging


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("AZFlow")


def main() -> None:
    """Entry point for ``python -m AZFlow``.

    The application server is wired in a later step; for now this simply
    confirms the package is runnable.
    """
    logger.info("AZFlow starting")


# let this be the last line of this file
logger.info("AZFlow loaded")
