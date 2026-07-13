"""The sp library.

The sp library brings sp notebooks to life with powerful
UI elements to interact with and transform data, dynamic markdown,
and more.

sp is designed to be:

    1. simple
    2. immersive
    3. interactive
    4. seamless
    5. fun
"""

# Deploy timing probe: source-level touch for notebook image rebuilds.

__all__ = [  # noqa: RUF022
    # Core API
    "App",
    "Cell",
    "AppMeta",
    "create_asgi_app",
    "SpIslandGenerator",
    "SpStopError",
    "Thread",
    "current_thread",
    # Data SDK
    "init",
    "connections",
    "connect",
    # Agent SDK
    "agent",
    # Other namespaces
    "ui",
    "islands",
    # Application elements
    "accordion",
    "app_meta",
    "as_html",
    "audio",
    "cache",
    "callout",
    "capture_stderr",
    "capture_stdout",
    "carousel",
    "center",
    "cli_args",
    "defs",
    "doc",
    "download",
    "hstack",
    "Html",
    "icon",
    "iframe",
    "image",
    "image_compare",
    "inspect",
    "json",
    "latex",
    "lazy",
    "left",
    "lru_cache",
    "md",
    "mermaid",
    "mpl",
    "nav_menu",
    "notebook_dir",
    "notebook_location",
    "outline",
    "output",
    "pdf",
    "persistent_cache",
    "plain",
    "plain_text",
    "query_params",
    "redirect_stderr",
    "redirect_stdout",
    "refs",
    "right",
    "routes",
    "running_in_notebook",
    "show_code",
    "sidebar",
    "sql",
    "stat",
    "state",
    "status",
    "stop",
    "style",
    "tabs",
    "tree",
    "video",
    "vstack",
    "watch",
    "__version__",
]
import signalpilot._islands as islands
from signalpilot._ast.app import App
from signalpilot._ast.cell import Cell
from signalpilot._islands._island_generator import SpIslandGenerator
from signalpilot._output.doc import doc
from signalpilot._output.formatting import as_html, iframe, plain
from signalpilot._output.hypertext import Html
from signalpilot._output.justify import center, left, right
from signalpilot._output.md import latex, md
from signalpilot._output.outline import outline
from signalpilot._output.show_code import show_code
from signalpilot._plugins import ui
from signalpilot._plugins.stateless import mpl, status
from signalpilot._plugins.stateless.accordion import accordion
from signalpilot._plugins.stateless.audio import audio
from signalpilot._plugins.stateless.callout import callout
from signalpilot._plugins.stateless.carousel import carousel
from signalpilot._plugins.stateless.download import download
from signalpilot._plugins.stateless.flex import hstack, vstack
from signalpilot._plugins.stateless.icon import icon
from signalpilot._plugins.stateless.image import image
from signalpilot._plugins.stateless.image_compare import image_compare
from signalpilot._plugins.stateless.inspect import inspect
from signalpilot._plugins.stateless.json_component import json
from signalpilot._plugins.stateless.lazy import lazy
from signalpilot._plugins.stateless.mermaid import mermaid
from signalpilot._plugins.stateless.nav_menu import nav_menu
from signalpilot._plugins.stateless.pdf import pdf
from signalpilot._plugins.stateless.plain_text import plain_text
from signalpilot._plugins.stateless.routes import routes
from signalpilot._plugins.stateless.sidebar import sidebar
from signalpilot._plugins.stateless.stat import stat
from signalpilot._plugins.stateless.style import style
from signalpilot._plugins.stateless.tabs import tabs
from signalpilot._plugins.stateless.tree import tree
from signalpilot._plugins.stateless.video import video
from signalpilot._runtime import output, watch
from signalpilot._runtime.app_meta import AppMeta
from signalpilot._runtime.capture import (
    capture_stderr,
    capture_stdout,
    redirect_stderr,
    redirect_stdout,
)
from signalpilot._runtime.context.utils import running_in_notebook
from signalpilot._runtime.control_flow import SpStopError, stop
from signalpilot._runtime.runtime import (
    app_meta,
    cli_args,
    defs,
    notebook_dir,
    notebook_location,
    query_params,
    refs,
)
from signalpilot._runtime.state import state
from signalpilot._runtime.threads import Thread, current_thread
from signalpilot._save.save import cache, lru_cache, persistent_cache
from signalpilot._server.asgi import create_asgi_app
from signalpilot._client.agent import agent
from signalpilot._sdk import connect, connections, init
from signalpilot._sql.sql import sql
from signalpilot._version import __version__
