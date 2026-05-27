FROM python:3.13-slim

RUN groupadd -g 10001 notebook && \
    useradd -r -u 10001 -g notebook notebook && \
    mkdir -p /workspace /home/notebook/.sp && \
    apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

WORKDIR /opt/sp-notebook
COPY pyproject.toml uv.lock MANIFEST.in .python-version README.md LICENSE ./
COPY signalpilot/ signalpilot/

# Use uv to install — it understands uv_build backend natively
RUN uv sync --frozen --no-dev && \
    uv pip install --no-cache \
      requests httpx starlette uvicorn msgspec \
      pydantic pydantic-settings websockets sse-starlette pyjwt \
      dbt-core dbt-duckdb duckdb polars pandas pyarrow numpy \
      sqlglot altair matplotlib plotly pyyaml jinja2 python-dotenv && \
    python -m compileall -q /opt/sp-notebook/signalpilot 2>/dev/null || true && \
    chown -R notebook:notebook /opt/sp-notebook /workspace /home/notebook

# uv installs into .venv by default — add it to PATH
ENV PATH="/opt/sp-notebook/.venv/bin:$PATH"

USER notebook
WORKDIR /workspace
EXPOSE 2718

HEALTHCHECK --interval=5s --timeout=3s --start-period=15s \
    CMD curl -sf http://localhost:2718/health || exit 1

CMD ["sp", "edit", "--host", "0.0.0.0", "--port", "2718", "--headless", "--no-token", "--no-skew-protection", "--allow-origins", "http://localhost:3200,http://localhost:3300", "/workspace"]
