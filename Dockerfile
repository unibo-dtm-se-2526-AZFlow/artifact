# AZFlow FastAPI application image

FROM python:3.13-slim

# Python settings
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=2.4.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Install Poetry for dependency management.
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Install runtime dependencies first to leverage Docker layer caching.
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root

# Copy the application source and install the package itself.
COPY AZFlow ./AZFlow
RUN poetry install --only main

# Default API port (overridable via AZFLOW_API_PORT).
EXPOSE 8000

CMD ["python", "-m", "AZFlow"]
