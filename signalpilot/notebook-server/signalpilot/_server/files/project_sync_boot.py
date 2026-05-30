"""Boot-time workspace clone. Invoked by pod CMD before `sp edit` starts."""

from __future__ import annotations

import logging
import os
import sys

from signalpilot._server.files.project_sync import (
    _validate_branch,
    _validate_project_id,
    sync_down,
)

_log = logging.getLogger("signalpilot.boot")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[boot] %(message)s")
    project_id = os.environ.get("SP_PROJECT_ID", "").strip()
    branch = os.environ.get("SP_BRANCH", "main").strip() or "main"

    if not project_id:
        # No project bound (scratch session). Skip the git clone and start with
        # an empty /workspace — the user can create or open a project later.
        _log.info("No SP_PROJECT_ID — starting scratch session with empty workspace")
        return 0

    try:
        _validate_project_id(project_id)
    except ValueError as exc:
        _log.error("Invalid SP_PROJECT_ID: %s", exc)
        return 1

    try:
        _validate_branch(branch)
    except ValueError as exc:
        _log.error("Invalid SP_BRANCH: %s", exc)
        return 1

    result = sync_down(project_id, branch)
    if result.get("error"):
        _log.error("sync_down failed: %s", result["error"])
        return 1
    _log.info("workspace ready at %s", result.get("local_dir"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
