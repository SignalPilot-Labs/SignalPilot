FROM python:3.12-slim

WORKDIR /app

# Install build deps, then clean up apt cache to reduce image size.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY workspaces_api/ ./workspaces_api/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN pip install --no-cache-dir .

# Run migrations first, then start the API server.
# restart: on-failure in compose means a migration error surfaces instead of looping.
CMD alembic upgrade head && \
    uvicorn workspaces_api.main:app --host 0.0.0.0 --port 3400
