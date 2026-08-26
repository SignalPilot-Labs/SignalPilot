"""Factory for creating the appropriate kernel and queue managers.

Dispatches to one of three strategies based on mode and sandbox config:
1. AppHost — RUN mode with app host isolation (multi-app process pool)
2. IPC/Sandbox — EDIT mode with SandboxMode.MULTI (ZeroMQ subprocess)
3. Original — Process for EDIT (SIGINT support), Thread for RUN (low memory)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot import _loggers
from signalpilot._session.managers.kernel import KernelManagerImpl
from signalpilot._session.managers.queue import QueueManagerImpl
from signalpilot._session.model import SessionMode
from signalpilot._session.types import KernelManager, QueueManager

if TYPE_CHECKING:
    from signalpilot._ast.cell import CellConfig
    from signalpilot._cli.sandbox import SandboxMode
    from signalpilot._config.manager import SpConfigManager
    from signalpilot._runtime.commands import AppMetadata
    from signalpilot._runtime.virtual_file import VirtualFileStorageType
    from signalpilot._session.notebook.file_manager import AppFileManager
    from signalpilot._session.session import AppHostContext
    from signalpilot._types.ids import CellId_t

LOGGER = _loggers.sp_logger()


def create_kernel_and_queues(
    *,
    mode: SessionMode,
    configs: dict[CellId_t, CellConfig],
    app_metadata: AppMetadata,
    config_manager: SpConfigManager,
    virtual_file_storage: VirtualFileStorageType | None,
    redirect_console_to_browser: bool,
    sandbox_mode: SandboxMode | None,
    app_host_context: AppHostContext | None,
    app_file_manager: AppFileManager,
) -> tuple[QueueManager, KernelManager]:
    """Create the appropriate queue and kernel managers for the session."""
    if app_host_context is not None and mode == SessionMode.RUN:
        return _create_app_host_managers(
            app_host_context=app_host_context,
            app_file_manager=app_file_manager,
            mode=mode,
            configs=configs,
            app_metadata=app_metadata,
            config_manager=config_manager,
            redirect_console_to_browser=redirect_console_to_browser,
        )

    from signalpilot._cli.sandbox import SandboxMode as SandboxModeEnum
    if sandbox_mode is SandboxModeEnum.MULTI:
        return _create_ipc_managers(
            mode=mode,
            configs=configs,
            app_metadata=app_metadata,
            config_manager=config_manager,
            redirect_console_to_browser=redirect_console_to_browser,
        )

    return _create_original_managers(
        mode=mode,
        configs=configs,
        app_metadata=app_metadata,
        config_manager=config_manager,
        virtual_file_storage=virtual_file_storage,
        redirect_console_to_browser=redirect_console_to_browser,
    )


def _create_app_host_managers(
    *,
    app_host_context: AppHostContext,
    app_file_manager: AppFileManager,
    mode: SessionMode,
    configs: dict[CellId_t, CellConfig],
    app_metadata: AppMetadata,
    config_manager: SpConfigManager,
    redirect_console_to_browser: bool,
) -> tuple[QueueManager, KernelManager]:
    """RUN mode with app host isolation (multi-app process pool)."""
    from signalpilot._session.managers.app_host import (
        AppHostKernelManager,
        AppHostQueueManager,
    )

    file_path = app_file_manager.path
    if file_path is None:
        raise ValueError("App host isolation requires a file-backed notebook")

    print(f"[FACTORY] Creating AppHost managers for {file_path}", flush=True)
    app_host = app_host_context.pool.get_or_create(file_path)
    queue_manager = AppHostQueueManager(app_host, app_host_context.session_id)
    kernel_manager = AppHostKernelManager(
        app_host=app_host,
        session_id=app_host_context.session_id,
        queue_manager=queue_manager,
        mode=mode,
        configs=configs,
        app_metadata=app_metadata,
        config_manager=config_manager,
        redirect_console_to_browser=redirect_console_to_browser,
    )
    return queue_manager, kernel_manager


def _create_ipc_managers(
    *,
    mode: SessionMode,
    configs: dict[CellId_t, CellConfig],
    app_metadata: AppMetadata,
    config_manager: SpConfigManager,
    redirect_console_to_browser: bool,
) -> tuple[QueueManager, KernelManager]:
    """EDIT mode with SandboxMode.MULTI (ZeroMQ subprocess)."""
    from signalpilot._ipc import QueueManager as IPCQueueManager
    from signalpilot._session.managers import (
        IPCKernelManagerImpl,
        IPCQueueManagerImpl,
    )

    print("[FACTORY] Creating IPC/sandbox managers", flush=True)
    ipc_queue_manager, connection_info = IPCQueueManager.create()
    queue_manager = IPCQueueManagerImpl.from_ipc(ipc_queue_manager)
    kernel_manager = IPCKernelManagerImpl(
        queue_manager=queue_manager,
        connection_info=connection_info,
        mode=mode,
        configs=configs,
        app_metadata=app_metadata,
        config_manager=config_manager,
        redirect_console_to_browser=redirect_console_to_browser,
    )
    return queue_manager, kernel_manager


def _create_original_managers(
    *,
    mode: SessionMode,
    configs: dict[CellId_t, CellConfig],
    app_metadata: AppMetadata,
    config_manager: SpConfigManager,
    virtual_file_storage: VirtualFileStorageType | None,
    redirect_console_to_browser: bool,
) -> tuple[QueueManager, KernelManager]:
    """Default: Process for EDIT (SIGINT), Thread for RUN (low memory)."""
    use_multiprocessing = mode == SessionMode.EDIT
    print(f"[FACTORY] Creating original managers (mp={use_multiprocessing})", flush=True)
    queue_manager = QueueManagerImpl(use_multiprocessing=use_multiprocessing)
    kernel_manager = KernelManagerImpl(
        queue_manager=queue_manager,
        mode=mode,
        configs=configs,
        app_metadata=app_metadata,
        config_manager=config_manager,
        virtual_file_storage=virtual_file_storage,
        redirect_console_to_browser=redirect_console_to_browser,
    )
    return queue_manager, kernel_manager
