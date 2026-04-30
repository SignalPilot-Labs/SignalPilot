# SignalPilot Sandbox -- gVisor (runsc)
# No hypervisor required. Works on Linux, macOS (Docker Desktop), CI.
#
# BUILD:
#   docker build -t signalpilot/sandbox .
#
# RUN:
#   docker run --cap-add SYS_PTRACE --cap-add SYS_ADMIN -p 8080:8080 signalpilot/sandbox

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV GVISOR_VERSION=20260323.0

# System deps (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install gVisor (runsc) -- pinned version, auto-detect architecture
RUN ARCH=$(uname -m) && \
    curl -fsSL "https://storage.googleapis.com/gvisor/releases/release/${GVISOR_VERSION}/${ARCH}/runsc" \
    -o /usr/local/bin/runsc && \
    chmod +x /usr/local/bin/runsc

RUN mkdir -p /opt/signalpilot

COPY pyproject.toml /opt/signalpilot/
RUN pip install --no-cache-dir /opt/signalpilot/

COPY constants.py /opt/signalpilot/
COPY models.py /opt/signalpilot/
COPY executor.py /opt/signalpilot/
COPY sandbox_manager.py /opt/signalpilot/

WORKDIR /opt/signalpilot

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["python3", "sandbox_manager.py"]
