# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import threading
from typing import Any

from signalpilot._messaging.streams import ThreadSafeStream
from signalpilot._output.rich_help import mddoc
from signalpilot._runtime.cell_lifecycle_item import CellLifecycleItem
from signalpilot._runtime.cell_output_list import CellOutputList
from signalpilot._runtime.context.kernel_context import KernelRuntimeContext
from signalpilot._runtime.context.script_context import ScriptRuntimeContext
from signalpilot._runtime.context.types import (
    ExecutionContext,
    RuntimeContext,
    get_context,
    initialize_context,
    runtime_context_installed,
    teardown_context,
)

# Set of thread ids for running sp.Threads
THREADS: set[int] = set()


@mddoc
class Thread(threading.Thread):
    """A Thread subclass that can communicate with the frontend.

    `sp.Thread` has the same API as threading.Thread,
    but `sp.Thread`s are able to communicate with the sp
    frontend, whereas `threading.Thread` can't.

    Threads can append to a cell's output using `sp.output.append`, or to the
    console output area using `print`. The corresponding outputs will be
    forwarded to the frontend.

    Writing directly to sys.stdout or sys.stderr, or to file descriptors 1 and
    2, is not yet supported.

    **Thread lifecycle.** When the cell that spawned this thread is invalidated
    (re-run, deleted, interrupted, or otherwise errored), this thread's
    `should_exit` property will evaluate to `True`, at which point it
    is the developer's responsibility to clean up their thread.

    Examples:
        ```python
        def target():
            import time
            import signalpilot

            thread = sp.current_thread()
            while not thread.should_exit:
                time.sleep(1)
                print("hello")
        ```

        ```python
        import signalpilot

        sp.Thread(target=target).start()
        ```
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self._signalpilot_ctx: RuntimeContext | None = None
        exit_event = threading.Event()
        self._exit_event = exit_event

        if not runtime_context_installed():
            return

        class ThreadLifecycle(CellLifecycleItem):
            def create(self, context: RuntimeContext) -> None:
                del context

            def dispose(self, context: RuntimeContext, deletion: bool) -> bool:
                del context
                del deletion
                exit_event.set()
                return True

        ctx = get_context()
        ctx.cell_lifecycle_registry.add(ThreadLifecycle())

        if isinstance(ctx, KernelRuntimeContext):
            self._signalpilot_ctx = KernelRuntimeContext(**ctx.__dict__)
            # standard IO is not yet threadsafe
            self._signalpilot_ctx.stdout = None
            self._signalpilot_ctx.stderr = None
            if isinstance(ctx.stream, ThreadSafeStream):
                self._signalpilot_ctx.stream = type(ctx.stream)(
                    pipe=ctx.stream.pipe,
                    # TODO(akshayka): stdin is not threadsafe
                    input_queue=ctx.stream.input_queue,
                    cell_id=ctx.stream.cell_id,
                    redirect_console=False,
                )
            else:
                raise RuntimeError(
                    "Unsupported stream type " + str(type(ctx.stream))
                )
        elif isinstance(self._signalpilot_ctx, ScriptRuntimeContext):
            # Standard streams are not rerouted when running as a script, so no
            # need to set to None
            self._signalpilot_ctx = ScriptRuntimeContext(**ctx.__dict__)
            if isinstance(ctx.stream, ThreadSafeStream):
                self._signalpilot_ctx.stream = ThreadSafeStream(
                    pipe=ctx.stream.pipe,
                    input_queue=ctx.stream.input_queue,
                    cell_id=ctx.stream.cell_id,
                    redirect_console=False,
                )
            else:
                raise RuntimeError(
                    "Unsupported stream type " + str(type(ctx.stream))
                )

    @property
    def should_exit(self) -> bool:
        """Whether this thread should exit.

        Returns `True` when the cell that spawned this thread has been invalidated;
        for example, if the cell:

        - was re-run
        - was deleted
        - was interrupted

        then this property evaluates to True.

        It is the developer's responsibility to clean up and finish their
        thread when this flag is set. Retrieve the current `sp.Thread` with

        ```python
        import signalpilot

        sp.current_thread()
        ```
        """
        return self._exit_event.is_set()

    def run(self) -> None:
        if self._signalpilot_ctx is not None:
            try:
                initialize_context(self._signalpilot_ctx)
            except RuntimeError:
                pass

        output = CellOutputList()
        if self._signalpilot_ctx is not None:
            if (exec_ctx := self._signalpilot_ctx.execution_context) is not None:
                # Share the parent's CellOutputList so appends from threads
                # are visible to the main execution context.
                output = exec_ctx.output

        if isinstance(self._signalpilot_ctx, KernelRuntimeContext):
            self._signalpilot_ctx.execution_context = ExecutionContext(
                cell_id=self._signalpilot_ctx.stream.cell_id,  # type: ignore
                setting_element_value=False,
                output=output,
            )
        thread_id = threading.get_ident()
        THREADS.add(thread_id)
        super().run()
        THREADS.remove(thread_id)
        teardown_context()


def current_thread() -> Thread:
    """Return the `sp.Thread` object for the caller's thread of control.

    Returns:
        The current `sp.Thread` object.

    Raises:
        RuntimeError: If the current thread of control is not a `sp.Thread`.
    """
    thread = threading.current_thread()
    if not isinstance(thread, Thread):
        raise RuntimeError(
            "sp.current_thread() must be called from a "
            "thread created with sp.Thread."
        )
    return thread


def is_sp_thread() -> bool:
    try:
        current_thread()
        return True
    except RuntimeError:
        return False
