from pathlib import Path

from signalpilot._server.workspace import SpFileKey


def resolve_project_file(local_dir: Path, file_key: SpFileKey) -> SpFileKey | None:
    """Resolve an exact project-relative file within its synced directory."""
    root = local_dir.resolve()
    candidate = (root / file_key).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return SpFileKey(str(candidate))
