"""Kernel manager implementation using multiprocessing Process or threading Thread."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from multiprocessing import connection
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from signalpilot._session.managers._mp_context import get_mp_context
from signalpilot._session.managers.errors import KernelStartupError

from signalpilot import _loggers
from signalpilot._config.settings import GLOBAL_SETTINGS
from signalpilot._messaging.types import KernelMessage
from signalpilot._output.formatters.formatters import register_formatters
from signalpilot._runtime import commands, runtime
from signalpilot._session.model import SessionMode
from signalpilot._session.queue import ProcessLike
from signalpilot._session.types import KernelManager, QueueManager
from signalpilot._utils.print import print_
from signalpilot._utils.subprocess import try_kill_process_and_group
from signalpilot._utils.typed_connection import TypedConnection

if TYPE_CHECKING:
    from signalpilot._ast.cell import CellConfig
    from signalpilot._config.manager import SpConfigReader
    from signalpilot._runtime.commands import AppMetadata
    from signalpilot._runtime.virtual_file import VirtualFileStorageType
    from signalpilot._types.ids import CellId_t

LOGGER = _loggers.sp_logger()

_KERNEL_CONNECT_TIMEOUT_S = 30.0
_PROFILE_WAIT_TIMEOUT_S = 10.0


class KernelManagerImpl(KernelManager):
    """Kernel manager using multiprocessing Process or threading Thread.

    Uses Process for edit mode (allows SIGINT interrupts) and Thread for
    run mode (lower memory overhead).
    """

    def __init__(
        self,
        *,
        queue_manager: QueueManager,
        mode: SessionMode,
        configs: dict[CellId_t, CellConfig],
        app_metadata: AppMetadata,
        config_manager: SpConfigReader,
        virtual_file_storage: VirtualFileStorageType | None,
        redirect_console_to_browser: bool,
    ) -> None:
        self.kernel_task: ProcessLike | threading.Thread | None = None
        self.queue_manager = queue_manager
        self.mode = mode
        self.configs = configs
        self.app_metadata = app_metadata
        self.config_manager = config_manager
        self.redirect_console_to_browser = redirect_console_to_browser

        self._read_conn: TypedConnection[KernelMessage] | None = None
        self._virtual_file_storage = virtual_file_storage

    def start_kernel(self) -> None:
        is_edit_mode = self.mode == SessionMode.EDIT
        listener = None
        if is_edit_mode:
            LOGGER.info(
                "Kernel start: creating listener (mode=%s, file=%s)",
                self.mode, self.app_metadata.filename,
            )
            listener = connection.Listener(family="AF_INET")
            LOGGER.info("Kernel start: listener at %s", listener.address)
            self.kernel_task = get_mp_context().Process(
                target=runtime.launch_kernel,
                args=(
                    self.queue_manager.control_queue,
                    self.queue_manager.set_ui_element_queue,
                    self.queue_manager.completion_queue,
                    self.queue_manager.input_queue,
                    None,
                    listener.address,
                    is_edit_mode,
                    self.configs,
                    self.app_metadata,
                    self.config_manager.get_config(hide_secrets=False),
                    self._virtual_file_storage,
                    self.redirect_console_to_browser,
                    self.queue_manager.win32_interrupt_queue,
                    self.profile_path,
                    GLOBAL_SETTINGS.LOG_LEVEL,
                    False,
                    os.getpid(),
                ),
                daemon=False,
            )
        else:
            def launch_kernel_with_cleanup(*args: Any) -> None:
                runtime.launch_kernel(*args)

            register_formatters(theme=self.config_manager.theme)

            if self.redirect_console_to_browser:
                from signalpilot._messaging.thread_local_streams import (
                    install_thread_local_proxies,
                )
                install_thread_local_proxies()

            assert self.queue_manager.stream_queue is not None
            self.kernel_task = threading.Thread(
                target=launch_kernel_with_cleanup,
                args=(
                    self.queue_manager.control_queue,
                    self.queue_manager.set_ui_element_queue,
                    self.queue_manager.completion_queue,
                    self.queue_manager.input_queue,
                    self.queue_manager.stream_queue,
                    None,
                    is_edit_mode,
                    self.configs,
                    self.app_metadata,
                    self.config_manager.get_config(hide_secrets=False),
                    self._virtual_file_storage,
                    self.redirect_console_to_browser,
                    None,
                    None,
                    GLOBAL_SETTINGS.LOG_LEVEL,
                ),
                daemon=True,
            )

        LOGGER.info("Starting kernel task (parent pid=%d)", os.getpid())
        self.kernel_task.start()  # type: ignore
        LOGGER.info(
            "Kernel task started (pid=%s, alive=%s)",
            getattr(self.kernel_task, "pid", "thread"),
            self.kernel_task.is_alive(),
        )

        if listener is not None:
            self._wait_for_kernel_connect(listener)

    def _wait_for_kernel_connect(self, listener: connection.Listener) -> None:
        """Wait for the kernel subprocess to connect back via the listener.

        Bounded by _KERNEL_CONNECT_TIMEOUT_S. Raises KernelStartupError
        if the kernel dies or times out before connecting.
        """
        result: dict[str, Any] = {}

        def _accept() -> None:
            try:
                result["conn"] = listener.accept()
            except Exception as e:
                result["error"] = e

        accept_thread = threading.Thread(
            target=_accept, name="kernel-accept", daemon=True
        )
        accept_thread.start()
        t0 = time.monotonic()

        while True:
            accept_thread.join(timeout=0.5)
            elapsed = time.monotonic() - t0

            if not accept_thread.is_alive():
                LOGGER.info("Kernel connected after %.1fs", elapsed)
                break

            kernel_alive = self.kernel_task.is_alive()  # type: ignore[attr-defined]
            exitcode = getattr(self.kernel_task, "exitcode", None)

            if int(elapsed) % 5 == 0 and elapsed > 1:
                LOGGER.info(
                    "Waiting for kernel connect (%.1fs, alive=%s, exitcode=%s)",
                    elapsed, kernel_alive, exitcode,
                )

            if not kernel_alive:
                LOGGER.error(
                    "Kernel died before connecting (exitcode=%s, %.1fs)",
                    exitcode, elapsed,
                )
                listener.close()
                accept_thread.join(timeout=1.0)
                raise KernelStartupError(
                    f"Kernel subprocess exited before connecting "
                    f"(exitcode={exitcode}); check subprocess stderr"
                )

            if elapsed >= _KERNEL_CONNECT_TIMEOUT_S:
                LOGGER.error(
                    "Kernel connect timeout after %.1fs (alive=%s)",
                    elapsed, kernel_alive,
                )
                listener.close()
                accept_thread.join(timeout=1.0)
                try_kill_process_and_group(self.kernel_task)
                raise KernelStartupError(
                    f"Kernel subprocess did not connect within "
                    f"{_KERNEL_CONNECT_TIMEOUT_S}s"
                )

        if "error" in result:
            LOGGER.error("Kernel accept error: %s", result["error"])
            raise result["error"]

        LOGGER.info("Kernel IPC connection established")
        self._read_conn = TypedConnection[KernelMessage].of(result["conn"])

    @property
    def pid(self) -> int | None:
        if self.kernel_task is None:
            return None
        if isinstance(self.kernel_task, threading.Thread):
            return None
        return self.kernel_task.pid

    @property
    def profile_path(self) -> str | None:
        self._profile_path: str | None

        if hasattr(self, "_profile_path"):
            return self._profile_path

        profile_dir = GLOBAL_SETTINGS.PROFILE_DIR
        if profile_dir is not None:
            self._profile_path = os.path.join(
                profile_dir,
                (
                    os.path.basename(self.app_metadata.filename) + str(uuid4())
                    if self.app_metadata.filename is not None
                    else str(uuid4())
                ),
            )
        else:
            self._profile_path = None
        return self._profile_path

    def is_alive(self) -> bool:
        return self.kernel_task is not None and self.kernel_task.is_alive()

    def interrupt_kernel(self) -> None:
        if self.kernel_task is None:
            return

        if isinstance(self.kernel_task, threading.Thread):
            return

        if self.kernel_task.pid is not None:
            q = self.queue_manager.win32_interrupt_queue
            if sys.platform == "win32" and q is not None:
                LOGGER.debug("Queueing interrupt request for kernel.")
                q.put_nowait(True)
            else:
                LOGGER.debug("Sending SIGINT to kernel")
                os.kill(self.kernel_task.pid, signal.SIGINT)

    def close_kernel(self) -> None:
        assert self.kernel_task is not None, "kernel not started"

        if isinstance(self.kernel_task, threading.Thread):
            if self.kernel_task.is_alive():
                self.queue_manager.put_control_request(
                    commands.StopKernelCommand()
                )
            return

        if self.profile_path is not None and self.kernel_task.is_alive():
            self.queue_manager.put_control_request(
                commands.StopKernelCommand()
            )
            print_(
                "\tWriting profile statistics to",
                self.profile_path,
                " ...",
            )
            t0 = time.monotonic()
            while not os.path.exists(self.profile_path):
                if time.monotonic() - t0 > _PROFILE_WAIT_TIMEOUT_S:
                    LOGGER.warning(
                        "Profile file not written after %.0fs, proceeding with cleanup",
                        _PROFILE_WAIT_TIMEOUT_S,
                    )
                    break
                time.sleep(0.1)
            time.sleep(1)

        self.queue_manager.close_queues()
        try:
            try_kill_process_and_group(self.kernel_task)
        except ProcessLookupError:
            pass
        except Exception as e:
            LOGGER.warning(e)
        if self._read_conn is not None:
            self._read_conn.close()

    @property
    def kernel_connection(self) -> TypedConnection[KernelMessage]:
        assert self._read_conn is not None, "connection not started"
        return self._read_conn
