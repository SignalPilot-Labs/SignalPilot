from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any

from signalpilot._ast.app import AppKernelRunnerRegistry
from signalpilot._cli.parse_args import args_from_argv
from signalpilot._config.config import SpConfig
from signalpilot._config.manager import get_default_config_manager
from signalpilot._plugins.ui._core.ids import NoIDProviderException
from signalpilot._plugins.ui._core.registry import UIElementRegistry
from signalpilot._runtime.cell_lifecycle_registry import CellLifecycleRegistry
from signalpilot._runtime.context.types import (
    ExecutionContext,
    RuntimeContext,
    initialize_context,
)
from signalpilot._runtime.dataflow import DirectedGraph
from signalpilot._runtime.functions import FunctionRegistry
from signalpilot._runtime.params import CLIArgs, QueryParams
from signalpilot._runtime.patches import (
    create_main_module,
    patch_main_module_context,
)
from signalpilot._runtime.state import State, StateRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from signalpilot._ast.app import InternalApp
    from signalpilot._messaging.types import Stream
    from signalpilot._types.ids import CellId_t


@dataclass
class ScriptRuntimeContext(RuntimeContext):
    """Encapsulates runtime state when running as a script."""

    _app: InternalApp

    def __post_init__(self) -> None:
        self._cli_args: CLIArgs | None = None
        self._argv = sys.argv
        self._query_params = QueryParams({}, _registry=self.state_registry)

    @property
    def graph(self) -> DirectedGraph:
        return self._app.graph

    @property
    def globals(self) -> dict[str, Any]:
        with patch_main_module_context(
            create_main_module(
                file=None, input_override=None, print_override=None
            )
        ) as module:
            glbls = module.__dict__
        glbls.update(sys.modules["__main__"].__dict__)
        return glbls

    @property
    def execution_context(self) -> ExecutionContext | None:
        return self._app.execution_context

    @cached_property
    def _cached_config(self) -> SpConfig:
        return get_default_config_manager(
            current_path=self.filename
        ).get_config()

    @property
    def signalpilot_config(self) -> SpConfig:
        return self._cached_config

    @property
    def cell_id(self) -> CellId_t | None:
        """Get the cell id of the currently executing cell, if any."""
        if self.execution_context is not None:
            return self.execution_context.cell_id
        return None

    @property
    def cli_args(self) -> CLIArgs:
        """Get the CLI args."""
        if self._cli_args is None:
            self._cli_args = CLIArgs(args_from_argv())
        return self._cli_args

    @property
    def argv(self) -> list[str]:
        """Get the original argv."""
        return self._argv

    @property
    def query_params(self) -> QueryParams:
        """Get the query params."""
        return self._query_params

    def get_ui_initial_value(self, object_id: str) -> Any:
        del object_id
        raise KeyError

    @contextmanager
    def provide_ui_ids(self, prefix: str) -> Iterator[None]:
        del prefix
        yield

    def take_id(self) -> str:
        raise NoIDProviderException

    def register_state_update(self, state: State[Any]) -> None:
        del state
        return

    @contextmanager
    def with_cell_id(self, cell_id: CellId_t) -> Iterator[None]:
        old = self.execution_context
        try:
            if old is not None:
                setting_element_value = old.setting_element_value
            else:
                setting_element_value = False
            self._app.set_execution_context(
                ExecutionContext(
                    cell_id=cell_id,
                    setting_element_value=setting_element_value,
                )
            )
            yield
        finally:
            self._app.set_execution_context(old)

    @property
    def app(self) -> InternalApp:
        return self._app


def initialize_script_context(
    app: InternalApp, stream: Stream, filename: str | None
) -> None:
    """Initializes thread-local/session-specific context.

    Must be called exactly once for each client thread.
    """
    from signalpilot._runtime.virtual_file import (
        InMemoryStorage,
        VirtualFileRegistry,
    )
    from signalpilot._save.cache import CacheState
    from signalpilot._save.stores import get_store

    runtime_context = ScriptRuntimeContext(
        _app=app,
        ui_element_registry=UIElementRegistry(),
        state_registry=StateRegistry(),
        function_registry=FunctionRegistry(),
        cache=CacheState(store=get_store(filename)),
        cell_lifecycle_registry=CellLifecycleRegistry(),
        app_kernel_runner_registry=AppKernelRunnerRegistry(),
        virtual_file_registry=VirtualFileRegistry(storage=InMemoryStorage()),
        virtual_files_supported=False,
        stream=stream,
        stdout=None,
        stderr=None,
        children=[],
        parent=None,
        filename=filename,
        app_config=app.config,
    )
    initialize_context(runtime_context=runtime_context)
