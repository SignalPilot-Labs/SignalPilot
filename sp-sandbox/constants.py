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

# --- Validation ---
MAX_CODE_LENGTH = 1_000_000
MIN_TIMEOUT = 1
MAX_TIMEOUT = 300
