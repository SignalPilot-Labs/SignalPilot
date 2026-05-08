"""Magic values for the sandbox manager and executor."""

import os

# --- Server ---
HOST = os.environ.get("SP_SANDBOX_HOST", "0.0.0.0")
PORT = int(os.environ.get("SP_SANDBOX_PORT", "8080"))
MAX_VMS = int(os.environ.get("SP_MAX_VMS", "10"))

# --- Executor ---
RUNSC_PATH = os.environ.get("RUNSC_PATH", "/usr/local/bin/runsc")
PYTHON_PATH = os.environ.get("SANDBOX_PYTHON", "python3")
MAX_OUTPUT_BYTES = 1_000_000  # 1 MB stdout cap
GVISOR_WARNING_PREFIX = "*** Warning:"

# --- Kernel sessions ---
KERNEL_IDLE_TIMEOUT = int(os.environ.get("SP_KERNEL_IDLE_TIMEOUT", "600"))
MAX_SESSIONS = int(os.environ.get("SP_MAX_SESSIONS", "10"))
KERNEL_EXEC_PATH = os.environ.get("KERNEL_EXEC_PATH", "/opt/signalpilot/kernel_exec.sh")

# --- Validation ---
MAX_CODE_LENGTH = 1_000_000
MIN_TIMEOUT = 1
MAX_TIMEOUT = 300
