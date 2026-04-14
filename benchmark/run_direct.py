"""Back-compat shim — the real implementation lives in benchmark.runners.direct.

Kept so that existing invocations still work:
    python -m benchmark.run_direct chinook001
    python benchmark/run_direct.py chinook001
"""

from __future__ import annotations

from benchmark.runners.direct import main

if __name__ == "__main__":
    main()
