from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from starlette.exceptions import HTTPException

from signalpilot._server.files.path_validator import PathValidator
from signalpilot._utils.http import HTTPStatus

_SEMANTIC_NOTEBOOK_EXTENSIONS = frozenset({".py", ".md", ".qmd"})


@dataclass(frozen=True)
class ResolvedNotebookFile:
    path: Path
    raw_fallback: bool


def resolve_safe_file_path(raw_file: str, directory: str | Path | None) -> Path:
    if directory is None:
        raise HTTPException(HTTPStatus.BAD_REQUEST, "no workspace configured")

    root = Path(directory)
    candidate = Path(raw_file)
    if not candidate.is_absolute():
        candidate = root / candidate
    PathValidator().validate_inside_directory(root, candidate)
    return candidate.resolve(strict=False)


def resolve_notebook_file(
    raw_file: str,
    directory: str | Path | None,
) -> ResolvedNotebookFile:
    """Resolve a workspace file and classify it without starting a kernel."""
    resolved = resolve_safe_file_path(raw_file, directory)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)

    raw_fallback = True
    if resolved.suffix.lower() in _SEMANTIC_NOTEBOOK_EXTENSIONS:
        try:
            if (
                resolved.suffix.lower() in {".md", ".qmd"}
                and b"sp-version:" not in resolved.read_bytes()[:512]
            ):
                return ResolvedNotebookFile(
                    path=resolved,
                    raw_fallback=True,
                )

            from signalpilot._ast.load import get_notebook_status

            load_result = get_notebook_status(str(resolved))
            raw_fallback = not (
                load_result.status in {"valid", "has_warnings"}
                and load_result.notebook is not None
                and len(load_result.notebook.cells) > 0
            )
        except Exception:
            raw_fallback = True

    return ResolvedNotebookFile(
        path=resolved,
        raw_fallback=raw_fallback,
    )
