from __future__ import annotations

ANALYSIS_BRANCH_PREFIX = "analysis/"
ANALYSIS_NOTEBOOK_RELPATH_PREFIXES = {
    "notion": "notebooks/notion/",
    "slack": "notebooks/slack/",
}


def is_generated_analysis_trail_notebook(
    *,
    project_id: str | None,
    branch: str | None,
    file_key: str | None,
) -> bool:
    """Return True for project-backed generated Slack/Notion analysis trails."""
    if not project_id or not branch or not file_key:
        return False
    if not branch.startswith(ANALYSIS_BRANCH_PREFIX):
        return False

    normalized = file_key.replace("\\", "/").lstrip("/")
    return any(
        branch.startswith(f"{ANALYSIS_BRANCH_PREFIX}{source}/")
        and normalized.startswith(prefix)
        for source, prefix in ANALYSIS_NOTEBOOK_RELPATH_PREFIXES.items()
    )
