"""Test configuration — ensures the repo root is on sys.path so that
the signalpilot namespace package is importable without installation."""

import os
import sys

# Insert the repo root so that `signalpilot.gateway.gateway.*` resolves via
# the namespace-package directory structure.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
