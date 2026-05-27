# Copyright 2026 SignalPilot. All rights reserved.
"""Public API for rendering sp notebooks as static HTML.

This module provides a clean, public API for rendering sp notebooks
to self-contained static HTML.  For the live editor, the frontend
fetches mount config from ``GET /api/mount-config`` instead.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, cast

from signalpilot._ast.app_config import _AppConfig
from signalpilot._config.config import PartialSignalPilotConfig, SpConfig
from signalpilot._convert.converters import SpConvert
from signalpilot._schemas.notebook import NotebookV1
from signalpilot._schemas.session import NotebookSessionV1
from signalpilot._server.templates.templates import static_notebook_template
from signalpilot._server.tokens import SkewProtectionToken
from signalpilot._utils.code import hash_code


@functools.lru_cache(maxsize=1)
def _get_html_template() -> str:
    """Get the base HTML template."""
    from signalpilot._utils.paths import sp_package_path

    index_html = Path(sp_package_path()) / "_static" / "index.html"
    return index_html.read_text(encoding="utf-8")


def _parse_config(config: dict[str, Any] | None) -> SpConfig:
    """Parse config dict to SpConfig."""
    if config is None:
        return cast(SpConfig, {})
    return cast(SpConfig, config)


def _parse_partial_config(
    config: dict[str, Any] | None,
) -> PartialSignalPilotConfig:
    """Parse config dict to PartialSignalPilotConfig."""
    if config is None:
        return cast(PartialSignalPilotConfig, {})
    return cast(PartialSignalPilotConfig, config)


def _convert_code_to_notebook(
    code: str,
) -> tuple[NotebookV1, _AppConfig]:
    """Convert Python code to notebook format."""
    try:
        ir = SpConvert.from_py(code)
    except Exception:
        ir = SpConvert.from_non_signalpilot_python_script(code, aggressive=True)

    app_config = _AppConfig.from_untrusted_dict(ir.ir.app.options)
    notebook = cast(NotebookV1, ir.to_notebook_v1())
    return notebook, app_config


def _parse_session_mode(mode: str) -> Any:
    from signalpilot._session.model import SessionMode

    if mode == "edit":
        return SessionMode.EDIT
    elif mode in ["run", "read"]:
        return SessionMode.RUN
    else:
        raise ValueError(
            f"Invalid session mode: {mode}. Must be 'edit' or 'run'."
        )


def render_static_notebook(
    *,
    code: str,
    filename: str | None = None,
    include_code: bool = True,
    session_snapshot: NotebookSessionV1,
    notebook_snapshot: NotebookV1 | None = None,
    files: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    app_config: dict[str, Any] | None = None,
    asset_url: str | None = None,
) -> str:
    """Render a static (pre-computed) sp notebook to HTML.

    Creates a fully self-contained HTML file with pre-computed outputs.
    Ideal for sharing read-only versions of notebooks.

    Args:
        code: Raw Python code as a string.
        filename: Display filename.
        include_code: Whether to include source code in the export.
        session_snapshot: Pre-computed outputs for all cells (required).
        notebook_snapshot: Notebook structure/metadata.
        files: Files to embed (key=path, value=base64 content).
        config: User configuration overrides.
        app_config: Notebook-specific configuration.
        asset_url: CDN URL for assets (default: jsDelivr).

    Returns:
        HTML string of the static notebook.

    Example:
        >>> html = render_static_notebook(
        ...     code=Path("analysis.py").read_text(),
        ...     session_snapshot=precomputed_outputs,
        ...     config={"theme": "dark"},
        ... )
    """

    if notebook_snapshot is None or app_config is None:
        converted_notebook, converted_app_config = _convert_code_to_notebook(
            code
        )
        if notebook_snapshot is None:
            notebook_snapshot = converted_notebook
        if app_config is None:
            app_config = converted_app_config.asdict()

    user_config = _parse_config(config)
    config_overrides_obj = _parse_partial_config(config or {})
    app_config_obj = _AppConfig.from_untrusted_dict(app_config)

    html = _get_html_template()

    return static_notebook_template(
        html=html,
        user_config=user_config,
        config_overrides=config_overrides_obj,
        server_token=SkewProtectionToken("static"),
        app_config=app_config_obj,
        filepath=filename,
        code=code if include_code else "",
        code_hash=hash_code(code),
        session_snapshot=session_snapshot,
        notebook_snapshot=notebook_snapshot,
        files=files or {},
        asset_url=asset_url,
    )


__all__ = [
    "render_static_notebook",
]
