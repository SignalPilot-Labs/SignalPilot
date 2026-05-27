# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import functools
import html
import json
import os
import re
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Literal, cast

from signalpilot._ast.app_config import _AppConfig
from signalpilot._config.config import PartialSignalPilotConfig, SpConfig
from signalpilot._messaging.notification import ModelLifecycleNotification
from signalpilot._output.utils import uri_encode_component
from signalpilot._schemas.notebook import NotebookV1
from signalpilot._schemas.session import NotebookSessionV1
from signalpilot._server.api.utils import parse_title
from signalpilot._server.tokens import SkewProtectionToken
from signalpilot._session.notebook import read_css_file, read_html_head_file
from signalpilot._utils.versions import is_editable
from signalpilot._version import __version__

if TYPE_CHECKING:
    from signalpilot._server.files.lsp_workspace import LspWorkspace


_json_script_escapes = {
    ord(">"): "\\u003E",
    ord("<"): "\\u003C",
    ord("&"): "\\u0026",
}


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(text, quote=True)


def json_script(data: Any) -> str:
    # See https://github.com/django/django/blob/main/django/utils/html.py#L88C1-L92C2
    # Only escape values that can break out of a script tag
    return json.dumps(data, sort_keys=True).translate(_json_script_escapes)


def _export_context_block(*, notebook_code: str) -> str:
    """Emit the trusted export marker consumed by islands/export runtime code."""
    return dedent(
        f"""
    <script data-sp="true">
        Object.defineProperty(window, "__SIGNALPILOT_EXPORT_CONTEXT__", {{
            value: Object.freeze({{
                trusted: true,
                notebookCode: {json_script(notebook_code)},
            }}),
            writable: false,
            configurable: false,
        }});
    </script>
    """
    )


def _static_state_block(
    *, files: dict[str, str], model_notifications: list[Any]
) -> str:
    """Emit the static-export virtual file table as a frozen, non-configurable
    global. Locking the shape prevents notebook-authored content from
    redirecting `@file/...` fetches by mutating the map after emission."""
    return dedent(
        f"""
    <script data-sp="true">
        Object.defineProperty(window, "__SIGNALPILOT_STATIC__", {{
            value: Object.freeze({{
                files: Object.freeze({json_script(files)}),
                modelNotifications: Object.freeze({json_script(model_notifications)}),
            }}),
            writable: false,
            configurable: false,
        }});
    </script>
    """
    )


def build_mount_config_dict(
    *,
    filename: str | None,
    cwd: str | None = None,
    lsp_workspace: LspWorkspace | None = None,
    mode: Literal["edit", "home", "read", "gallery"],
    server_token: SkewProtectionToken,
    user_config: SpConfig,
    config_overrides: PartialSignalPilotConfig,
    app_config: _AppConfig | None,
    version: str | None = None,
    show_app_code: bool = True,
    session_snapshot: NotebookSessionV1 | None = None,
    notebook_snapshot: NotebookV1 | None = None,
    runtime_config: list[dict[str, Any]] | None = None,
    raw_fallback: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serializable dict for the mount config response.

    This is the single source of truth for both the live ``GET /api/mount-config``
    endpoint and the static/wasm export HTML injection.  The keys match the
    frontend ``mountOptionsSchema`` (camelCase) exactly.
    """
    return {
        "filename": filename or "",
        "cwd": cwd or "",
        "lspWorkspace": lsp_workspace,
        "mode": mode,
        "version": version or get_version(),
        "serverToken": str(server_token),
        "config": user_config,
        "configOverrides": config_overrides,
        "appConfig": _del_none_or_empty(app_config.asdict()) if app_config else {},
        "view": {"showAppCode": show_app_code},
        "notebook": notebook_snapshot,
        "session": session_snapshot,
        "runtimeConfig": runtime_config,
        "gatewayUrl": os.environ.get("SP_GATEWAY_PUBLIC_URL", "")
        or os.environ.get("SP_GATEWAY_URL", ""),
        "gatewayApiKey": os.environ.get("SP_SESSION_JWT", "")
        or os.environ.get("SP_API_KEY", ""),
        "rawFallback": raw_fallback,
    }


def static_notebook_template(
    html: str,
    user_config: SpConfig,
    config_overrides: PartialSignalPilotConfig,
    server_token: SkewProtectionToken,
    app_config: _AppConfig,
    filepath: str | None,
    code: str,
    code_hash: str,
    session_snapshot: NotebookSessionV1,
    notebook_snapshot: NotebookV1,
    files: dict[str, str],
    model_notifications: list[ModelLifecycleNotification] | None = None,
    asset_url: str | None = None,
) -> str:
    if asset_url is None:
        asset_url = f"https://cdn.jsdelivr.net/npm/@signalpilot-team/frontend@{__version__}/dist"

    html = html.replace("{{ base_url }}", "")
    filename = os.path.basename(filepath or "")
    html = html.replace("{{ filename }}", _html_escape(filename))

    mount_config = build_mount_config_dict(
        filename=filename,
        cwd=None,
        mode="read",
        server_token=server_token,
        user_config=user_config,
        config_overrides=config_overrides,
        app_config=app_config,
        session_snapshot=session_snapshot,
        notebook_snapshot=notebook_snapshot,
        runtime_config=None,
    )
    html = html.replace(
        "'{{ mount_config }}'",
        json_script(mount_config),
    )

    html = html.replace(
        "{{ title }}",
        _html_escape(
            parse_title(filepath)
            if app_config.app_title is None
            else app_config.app_title
        ),
    )

    static_block = _static_state_block(
        files=files,
        model_notifications=[
            n.to_json_serializable() for n in model_notifications or []
        ],
    )
    static_block += _export_context_block(notebook_code=code)

    if app_config.html_head_file:
        head_contents = read_html_head_file(
            app_config.html_head_file, filename=filepath
        )
        if head_contents:
            static_block += dedent(
                f"""
            {head_contents}
            """
            )

    if app_config.css_file:
        css_contents = read_css_file(app_config.css_file, filename=filepath)
        if css_contents:
            static_block += _custom_css_block(css_contents)

    static_block = _inject_custom_css_for_config(
        static_block, user_config, filepath
    )
    static_block = _inject_custom_css_for_config(
        static_block, config_overrides, filepath
    )

    code_block = dedent(
        f"""
    <sp-code hidden="">
        {uri_encode_component(code)}
    </sp-code>
    """
    )
    if not code:
        code_block = '<sp-code hidden=""></sp-code>'

    code_block += (
        f'\n<sp-code-hash hidden="">{code_hash}</sp-code-hash>\n'
    )

    # Replace all relative href and src with absolute URL
    html = _replace_asset_urls(html, asset_url)

    # Append to head
    html = html.replace("</head>", f"{static_block}</head>")
    # Append to body
    html = html.replace("</body>", f"{code_block}</body>")

    html = _inject_custom_css_for_config(html, user_config, filepath)
    html = _inject_custom_css_for_config(html, config_overrides, filepath)
    return html


def wasm_notebook_template(
    *,
    html: str,
    version: str,
    filename: str,
    user_config: SpConfig,
    config_overrides: PartialSignalPilotConfig,
    app_config: _AppConfig,
    mode: Literal["edit", "run"],
    code: str,
    show_code: bool,
    asset_url: str | None = None,
    session_snapshot: NotebookSessionV1 | None = None,
    notebook_snapshot: NotebookV1 | None = None,
) -> str:
    """Template for WASM notebooks."""
    import re

    body = html

    if asset_url is not None:
        body = re.sub(r'="./assets/', f'="{asset_url}/assets/', body)

    body = body.replace("{{ base_url }}", "")
    body = body.replace(
        "{{ title }}",
        _html_escape(
            parse_title(filename)
            if app_config.app_title is None
            else app_config.app_title
        ),
    )

    body = body.replace("{{ filename }}", _html_escape("notebook.py"))

    mount_config = build_mount_config_dict(
        filename="notebook.py",
        mode="edit" if mode == "edit" else "read",
        server_token=SkewProtectionToken("unused"),
        user_config=user_config,
        config_overrides=config_overrides,
        app_config=app_config,
        version=version,
        show_app_code=show_code,
        runtime_config=None,
        session_snapshot=session_snapshot,
        notebook_snapshot=notebook_snapshot,
    )
    body = body.replace(
        "'{{ mount_config }}'",
        json_script(mount_config),
    )

    body = body.replace(
        "</head>", '<sp-wasm hidden=""></sp-wasm></head>'
    )

    warning_script = """
    <script>
        if (window.location.protocol === 'file:') {
            alert('Warning: This file must be served by an HTTP server to function correctly.');
        }
    </script>
    """
    body = body.replace("</head>", f"{warning_script}</head>")

    wasm_styles = """
    <style>
        #save-button {
            display: none !important;
        }
        #filename-input {
            display: none !important;
        }
    </style>
    """
    body = body.replace("</head>", f"{wasm_styles}</head>")

    if app_config.css_file:
        css_contents = read_css_file(app_config.css_file, filename=filename)
        if css_contents:
            css_contents = _custom_css_block(css_contents)
            body = body.replace("</head>", f"{css_contents}</head>")

    body = _inject_custom_css_for_config(body, user_config, filename)
    body = _inject_custom_css_for_config(body, config_overrides, filename)

    if app_config.html_head_file:
        head_contents = read_html_head_file(
            app_config.html_head_file, filename=filename
        )
        if head_contents:
            body = body.replace("</head>", f"{head_contents}</head>")

    body = body.replace(
        "</head>",
        (
            f"{_export_context_block(notebook_code=code)}"
            f'<sp-code hidden="">{uri_encode_component(code)}</sp-code></head>'
        ),
    )

    return body


def _del_none_or_empty(d: Any) -> Any:
    return {
        key: (
            _del_none_or_empty(cast(Any, value))
            if isinstance(value, dict)
            else value
        )
        for key, value in d.items()
        if value is not None and value != []
    }


@functools.lru_cache(maxsize=1)
def get_version() -> str:
    return (
        f"{__version__} (editable)" if is_editable("sp") else __version__
    )


# HTML5 terminates a <style> raw-text element at the first "</style"
# (case-insensitive, optional whitespace). Neutralize that sequence so
# notebook-controlled CSS cannot break out of the block and inject HTML.
_STYLE_END_RE = re.compile(r"</(?=\s*style)", re.IGNORECASE)


def _sanitize_css_for_style_block(css_contents: str) -> str:
    return _STYLE_END_RE.sub(r"<\\/", css_contents)


def _custom_css_block(css_contents: str) -> str:
    safe = _sanitize_css_for_style_block(css_contents)
    return f"<style title='sp-custom'>{safe}</style>"


def _inject_custom_css_for_config(
    html: str,
    config: SpConfig | PartialSignalPilotConfig,
    filename: str | None = None,
) -> str:
    """Inject custom CSS from display config into HTML."""
    custom_css = config.get("display", {}).get("custom_css", [])
    if not custom_css:
        return html

    css_contents: list[str] = []
    for css_path in custom_css:
        css_content = read_css_file(css_path, filename=filename)
        if css_content:
            css_contents.append(_custom_css_block(css_content))

    if not css_contents:
        return html

    css_block = "\n".join(css_contents)
    return html.replace("</head>", f"{css_block}</head>")


def _replace_asset_urls(html: str, asset_url: str | None) -> str:
    """Replace relative asset URLs with the given CDN asset URL.

    Used only by static/wasm export templates, which still need to rewrite
    `./assets/` references to point at the CDN bundle.  The live editor's
    ``GET /`` no longer calls this function.
    """
    if asset_url is None:
        return html

    if "{version}" in asset_url:
        asset_url = asset_url.replace("{version}", __version__)

    return (
        html.replace("href='./", f"crossorigin='anonymous' href='{asset_url}/")
        .replace("src='./", f"crossorigin='anonymous' src='{asset_url}/")
        .replace('href="./', f'crossorigin="anonymous" href="{asset_url}/')
        .replace('src="./', f'crossorigin="anonymous" src="{asset_url}/')
    )
