from __future__ import annotations

import abc
import asyncio
import json
import os
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from signalpilot import _loggers
from signalpilot._server.api.auth import validate_auth
from signalpilot._server.api.deps import AppState
from signalpilot._server.codes import WebSocketCodes
from signalpilot._server.router import APIRouter
from signalpilot._session.model import SessionMode
from signalpilot._utils.platform import is_pyodide, is_windows

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

LOGGER = _loggers.sp_logger()

router = APIRouter()


# Configuration constants
MAX_CHUNK_SIZE = 8192
MAX_BUFFER_SIZE = 65536
MAX_COMMAND_BUFFER_SIZE = 1024
KEEP_COMMAND_CHARS = 512
HEALTH_CHECK_INTERVAL = 5.0
READ_TIMEOUT = 0.05
IDLE_SLEEP = 0.01


# ── Abstract PTY interface ─────────────────────────────────────

class PtyBackend(abc.ABC):
    @abc.abstractmethod
    def resize(self, rows: int, cols: int) -> None: ...

    @abc.abstractmethod
    def read(self, size: int = MAX_CHUNK_SIZE) -> bytes | None: ...

    @abc.abstractmethod
    def write(self, data: bytes) -> None: ...

    @abc.abstractmethod
    def cleanup(self) -> None: ...

    @abc.abstractmethod
    def wait_for_read(self, timeout: float) -> bool: ...


# ── Unix PTY backend ──────────────────────────────────────────

class UnixPtyBackend(PtyBackend):
    def __init__(self, child_pid: int, fd: int) -> None:
        self._child_pid = child_pid
        self._fd = fd

    def resize(self, rows: int, cols: int) -> None:
        try:
            import fcntl
            import termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
            LOGGER.debug(f"PTY resized to {cols}x{rows}")
        except Exception as e:
            LOGGER.warning(f"Failed to resize PTY: {e}")

        try:
            import signal
            os.kill(self._child_pid, signal.SIGWINCH)
        except (OSError, ProcessLookupError) as e:
            LOGGER.debug(f"Failed to send SIGWINCH to {self._child_pid}: {e}")

    def read(self, size: int = MAX_CHUNK_SIZE) -> bytes | None:
        try:
            chunk = os.read(self._fd, size)
            return chunk if chunk else None
        except OSError as e:
            if e.errno == 5:  # Input/output error (process died)
                return None
            raise

    def write(self, data: bytes) -> None:
        try:
            os.write(self._fd, data)
        except OSError as e:
            if e.errno == 5:
                raise EOFError("Process died") from e
            raise

    def wait_for_read(self, timeout: float) -> bool:
        import selectors
        sel = selectors.DefaultSelector()
        try:
            sel.register(self._fd, selectors.EVENT_READ)
            events = sel.select(timeout=timeout)
            return len(events) > 0
        finally:
            sel.close()

    def cleanup(self) -> None:
        import signal
        try:
            os.kill(self._child_pid, signal.SIGTERM)
            try:
                os.waitpid(self._child_pid, os.WNOHANG)
            except (OSError, ChildProcessError):
                pass
            try:
                os.kill(self._child_pid, signal.SIGKILL)
                os.waitpid(self._child_pid, 0)
            except (OSError, ProcessLookupError, ChildProcessError):
                pass
        except Exception as e:
            LOGGER.debug(f"Error during cleanup: {e}")
        try:
            os.close(self._fd)
        except OSError:
            pass


def _create_unix_pty(cwd: str | None = None) -> UnixPtyBackend:
    import pty

    shell, env = _create_unix_shell_environment()
    if cwd is None:
        cwd = env.get("PWD", os.getcwd())

    child_pid, fd = pty.fork()
    if child_pid == 0:
        # Child process
        try:
            os.chdir(cwd)
            os.execve(shell, [shell], env)
        except Exception as e:
            LOGGER.error(f"Failed to start shell: {e}")
            sys.exit(1)

    return UnixPtyBackend(child_pid, fd)


def _create_unix_shell_environment() -> tuple[str, dict[str, str]]:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["LANG"] = env.get("LANG", "en_US.UTF-8")
    env["LC_ALL"] = env.get("LC_ALL", "en_US.UTF-8")

    default_shell = os.environ.get("SHELL")
    if not default_shell or not os.path.exists(default_shell):
        for shell in ["/bin/bash", "/bin/zsh", "/bin/sh"]:
            if os.path.exists(shell):
                default_shell = shell
                break
        else:
            default_shell = "/bin/sh"

    return default_shell, env


# ── Windows PTY backend ───────────────────────────────────────

class WindowsPtyBackend(PtyBackend):
    """Windows PTY using pywinpty.

    pywinpty's read() blocks when no data is available, so the async
    read loop uses wait_for with a timeout instead of wait_for_read.
    """

    blocking_read = True

    def __init__(self, process: Any) -> None:
        self._process = process

    def resize(self, rows: int, cols: int) -> None:
        try:
            self._process.setwinsize(rows, cols)
            LOGGER.debug(f"PTY resized to {cols}x{rows}")
        except Exception as e:
            LOGGER.warning(f"Failed to resize PTY: {e}")

    def read(self, size: int = MAX_CHUNK_SIZE) -> bytes | None:
        try:
            data = self._process.read(size)
            if data:
                return data.encode("utf-8") if isinstance(data, str) else data
            return None
        except EOFError:
            return None
        except Exception as e:
            LOGGER.debug(f"Read error: {e}")
            return None

    def write(self, data: bytes) -> None:
        try:
            text = data.decode("utf-8", errors="replace")
            self._process.write(text)
        except EOFError:
            raise
        except Exception as e:
            LOGGER.debug(f"Write error: {e}")
            raise EOFError("Process died") from e

    def wait_for_read(self, timeout: float) -> bool:
        return self._process.isalive()

    def cleanup(self) -> None:
        try:
            if self._process.isalive():
                self._process.terminate()
        except Exception as e:
            LOGGER.debug(f"Error during cleanup: {e}")
        try:
            self._process.close()
        except Exception:
            pass


def _create_windows_pty(cwd: str | None = None) -> WindowsPtyBackend:
    from winpty import PtyProcess

    shell = _get_windows_shell()
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    if cwd is None:
        cwd = os.getcwd()

    process = PtyProcess.spawn(
        shell,
        cwd=cwd,
        env=env,
        dimensions=(24, 120),
    )

    return WindowsPtyBackend(process)


def _get_windows_shell() -> str:
    # Prefer PowerShell, fall back to cmd
    ps_path = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    if os.path.exists(ps_path):
        return ps_path

    return os.environ.get("COMSPEC", "cmd.exe")


# ── Shared read/write loops ──────────────────────────────────

def _decode_pty_data(
    buffer: bytes, max_buffer_size: int = MAX_BUFFER_SIZE
) -> tuple[str, bytes]:
    try:
        text = buffer.decode("utf-8", errors="ignore")
        return text, b""
    except UnicodeDecodeError:
        if len(buffer) > max_buffer_size:
            text = buffer.decode("utf-8", errors="replace")
            return text, b""
        return "", buffer


def _should_close_on_command(command_buffer: str, data: str) -> bool:
    if data in ["\r", "\n"]:
        return command_buffer.strip().lower() == "exit"
    return False


def _manage_command_buffer(
    buffer: str, data: str, max_size: int = MAX_COMMAND_BUFFER_SIZE
) -> str:
    buffer += data
    if len(buffer) > max_size:
        return buffer[-KEEP_COMMAND_CHARS:]
    return buffer


async def _read_from_pty(backend: PtyBackend, websocket: WebSocket) -> None:
    uses_blocking_read = getattr(backend, "blocking_read", False)

    if uses_blocking_read:
        await _read_from_pty_blocking(backend, websocket)
    else:
        await _read_from_pty_selectable(backend, websocket)


async def _read_from_pty_selectable(
    backend: PtyBackend, websocket: WebSocket,
) -> None:
    """Read loop for Unix PTYs that support non-blocking select."""
    loop = asyncio.get_running_loop()
    buffer = b""

    try:
        while True:
            try:
                has_data = await loop.run_in_executor(
                    None, backend.wait_for_read, READ_TIMEOUT,
                )
                if has_data:
                    try:
                        chunk = await loop.run_in_executor(
                            None, backend.read, MAX_CHUNK_SIZE,
                        )
                        if chunk is None:
                            break
                        buffer += chunk
                    except (OSError, EOFError):
                        break

                if buffer:
                    text, buffer = _decode_pty_data(buffer)
                    if text:
                        await websocket.send_text(text)
                else:
                    await asyncio.sleep(IDLE_SLEEP)

            except (asyncio.CancelledError, WebSocketDisconnect):
                break
    except OSError as e:
        if e.errno == 9:
            LOGGER.debug("File descriptor closed, stopping read loop")
            return
        raise


async def _read_from_pty_blocking(
    backend: PtyBackend, websocket: WebSocket,
) -> None:
    """Read loop for Windows PTYs where read() blocks.

    Uses a dedicated reader thread that pushes chunks into an asyncio
    queue, avoiding thread accumulation from repeated wait_for timeouts.
    """
    import queue
    import threading

    chunk_queue: queue.Queue[bytes | None] = queue.Queue()
    stop_event = threading.Event()

    def reader_thread() -> None:
        while not stop_event.is_set():
            try:
                chunk = backend.read(MAX_CHUNK_SIZE)
                if chunk is None:
                    chunk_queue.put(None)
                    return
                chunk_queue.put(chunk)
            except (OSError, EOFError):
                chunk_queue.put(None)
                return
            except Exception:
                chunk_queue.put(None)
                return

    thread = threading.Thread(target=reader_thread, daemon=True)
    thread.start()

    buffer = b""
    try:
        while True:
            try:
                # Drain all available chunks from the queue
                while True:
                    try:
                        chunk = chunk_queue.get_nowait()
                        if chunk is None:
                            # Process ended
                            if buffer:
                                text, buffer = _decode_pty_data(buffer)
                                if text:
                                    await websocket.send_text(text)
                            return
                        buffer += chunk
                    except queue.Empty:
                        break

                if buffer:
                    text, buffer = _decode_pty_data(buffer)
                    if text:
                        await websocket.send_text(text)
                else:
                    await asyncio.sleep(IDLE_SLEEP)

            except (asyncio.CancelledError, WebSocketDisconnect):
                break
    finally:
        stop_event.set()


class ResizeMessage(TypedDict):
    type: Literal["resize"]
    cols: int
    rows: int


async def _maybe_handle_resize(
    *, backend: PtyBackend, message: str
) -> bool:
    try:
        parsed_message: ResizeMessage = json.loads(message)
        if (
            isinstance(parsed_message, dict)
            and parsed_message.get("type") == "resize"
        ):
            cols = parsed_message.get("cols")
            rows = parsed_message.get("rows")
            if (
                isinstance(cols, int)
                and isinstance(rows, int)
                and cols > 0
                and rows > 0
            ):
                backend.resize(rows, cols)
                return True
            else:
                LOGGER.warning("Invalid resize message")
                return False
    except (json.JSONDecodeError, TypeError):
        pass
    return False


async def _write_to_pty(
    backend: PtyBackend, websocket: WebSocket,
) -> None:
    loop = asyncio.get_running_loop()
    try:
        command_buffer = ""
        while True:
            try:
                data = await websocket.receive_text()
                LOGGER.debug("Received: %s", repr(data))

                if await _maybe_handle_resize(
                    backend=backend, message=data
                ):
                    continue

                command_buffer = _manage_command_buffer(command_buffer, data)

                if _should_close_on_command(command_buffer, data):
                    LOGGER.debug("Exit command received, closing connection")
                    return

                if data in ["\r", "\n"]:
                    command_buffer = ""

                try:
                    encoded_data = data.encode("utf-8")
                    await loop.run_in_executor(
                        None, backend.write, encoded_data,
                    )
                except (OSError, EOFError):
                    LOGGER.debug("Process died, stopping write loop")
                    break

            except (asyncio.CancelledError, WebSocketDisconnect):
                break
    except OSError as e:
        if e.errno == 9:
            LOGGER.debug("File descriptor closed, stopping write loop")
            return
        raise


async def _cancel_tasks(tasks: Iterable[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ── Capability check ──────────────────────────────────────────

def supports_terminal() -> bool:
    """Whether the current environment supports terminals."""
    if is_pyodide():
        return False
    if is_windows():
        try:
            from winpty import PtyProcess  # noqa: F401
            return True
        except ImportError:
            return False
    # Unix
    try:
        import pty  # noqa: F401
        return True
    except ImportError:
        return False


def _create_pty_backend(cwd: str | None = None) -> PtyBackend:
    if is_windows():
        return _create_windows_pty(cwd)
    return _create_unix_pty(cwd)


# ── WebSocket endpoint ────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    app_state = AppState(websocket)

    if app_state.enable_auth and not validate_auth(websocket):
        await websocket.close(
            WebSocketCodes.UNAUTHORIZED, "SP_UNAUTHORIZED"
        )
        return

    if app_state.mode != SessionMode.EDIT:
        await websocket.close(
            code=1008, reason="Terminal only available in edit mode"
        )
        return

    if not supports_terminal():
        await websocket.close(
            code=1008, reason="Terminal not supported in this environment"
        )
        return

    try:
        await websocket.accept()
        LOGGER.debug("Terminal websocket accepted")
    except Exception as e:
        LOGGER.error(f"Failed to accept websocket connection: {e}")
        return

    # Use cwd from query param if provided
    cwd = websocket.query_params.get("cwd")
    if cwd and os.path.isdir(cwd):
        LOGGER.debug(f"Terminal cwd from query param: {cwd}")
    else:
        cwd = None

    try:
        backend = _create_pty_backend(cwd)
    except Exception as e:
        LOGGER.error(f"Failed to initialize terminal: {e}")
        try:
            if websocket.application_state != WebSocketState.DISCONNECTED:
                await websocket.close(
                    code=1011, reason="Failed to initialize terminal"
                )
        except Exception:
            pass
        return

    reader_task = asyncio.create_task(_read_from_pty(backend, websocket))
    writer_task = asyncio.create_task(_write_to_pty(backend, websocket))

    try:
        _done, pending = await asyncio.wait(
            [reader_task, writer_task], return_when=asyncio.FIRST_COMPLETED
        )
        await _cancel_tasks(pending)

    except WebSocketDisconnect:
        LOGGER.debug("Client disconnected from terminal")
    except Exception as e:
        LOGGER.exception(f"Terminal websocket error: {e}")
    finally:
        await _cancel_tasks([reader_task, writer_task])

        try:
            if websocket.application_state != WebSocketState.DISCONNECTED:
                await websocket.close(
                    code=1000, reason="Terminal session ended"
                )
        except Exception as e:
            LOGGER.debug(f"Error closing websocket: {e}")

        backend.cleanup()
    LOGGER.debug("Terminal websocket closed")
