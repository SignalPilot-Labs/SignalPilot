# Claude Code CLI agent box for the NALA "upstream break" trap.
# Mirrors benchmark/Dockerfile.ade-agent: node + claude-code CLI + dbt-postgres.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates build-essential libpq-dev postgresql-client jq \
    && rm -rf /var/lib/apt/lists/*

# Node.js (required for Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (pinned to the version the benchmark uses)
RUN npm install -g @anthropic-ai/claude-code@2.1.156

# dbt + postgres adapter so the agent CAN investigate/rebuild lineage if it chooses
RUN pip install --no-cache-dir "dbt-core==1.11.11" "dbt-postgres==1.9.0" pandas psycopg2-binary

# Non-root user (Claude CLI refuses to run as root without extra flags)
RUN useradd -m agent \
    && mkdir -p /home/agent/.claude /work \
    && echo '{}' > /home/agent/.claude.json \
    && chown -R agent:agent /home/agent /work
USER agent
RUN git config --global user.name "Analyst Agent" \
    && git config --global user.email "agent@noreply.com" \
    && git config --global --add safe.directory '*'

WORKDIR /work
ENTRYPOINT ["bash"]
