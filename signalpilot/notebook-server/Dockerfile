FROM python:3.13-slim

RUN groupadd -g 10001 notebook && \
    useradd -r -u 10001 -g notebook notebook && \
    mkdir -p /workspace /home/notebook/.sp && \
    apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sp-notebook

COPY . .

RUN pip install --no-cache-dir \
    -e . \
    "starlette==1.0.0" \
    "uvicorn==0.47.0" \
    "httpx==0.28.1" \
    "msgspec==0.21.1" \
    "pydantic==2.13.4" \
    "pydantic-settings==2.14.1" \
    "websockets==16.0" \
    "sse-starlette==3.4.4" \
    "pyjwt==2.12.1" \
    "dbt-core==1.11.10" \
    "dbt-duckdb==1.10.1" \
    "duckdb==1.5.2" \
    "polars>=1.0" \
    "pandas==3.0.3" \
    "pyarrow==24.0.0" \
    "numpy==2.4.4" \
    "sqlglot==30.8.0" \
    "altair==6.1.0" \
    "matplotlib==3.10.9" \
    "plotly==6.7.0" \
    "anthropic>=0.40" \
    "openai==2.36.0" \
    "mcp==1.27.1" \
    "pyyaml==6.0.3" \
    "jinja2==3.1.6" \
    "python-dotenv==1.2.2" \
    "requests==2.34.2" && \
    python -m compileall -q /opt/sp-notebook/signalpilot 2>/dev/null || true && \
    chown -R notebook:notebook /opt/sp-notebook /workspace /home/notebook

USER notebook
WORKDIR /workspace

EXPOSE 2718

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s \
    CMD curl -sf http://localhost:2718/api/health || exit 1

CMD ["sp", "edit", "--host", "0.0.0.0", "--port", "2718", "--headless", "--no-token", "--allow-origins", "*", "/workspace"]
