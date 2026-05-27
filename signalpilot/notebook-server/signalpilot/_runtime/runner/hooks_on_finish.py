from __future__ import annotations

from signalpilot import _loggers
from signalpilot._messaging.errors import (
    Error,
    SpAncestorPreventedError,
    SpAncestorStoppedError,
    SpExceptionRaisedError,
    SpInterruptionError,
    SpStrictExecutionError,
)
from signalpilot._messaging.notification_utils import CellNotificationUtils
from signalpilot._runtime.control_flow import SpStopError
from signalpilot._runtime.runner.hook_context import OnFinishHookContext
from signalpilot._runtime.runner.hooks import OnFinishHook
from signalpilot._tracer import kernel_tracer

LOGGER = _loggers.sp_logger()


@kernel_tracer.start_as_current_span("send_interrupt_errors")
def _send_interrupt_errors(ctx: OnFinishHookContext) -> None:
    if ctx.cells_to_run:
        assert ctx.interrupted
        for cid in ctx.cells_to_run:
            # `cid` was not run
            ctx.graph.cells[cid].set_runtime_state("idle")
            CellNotificationUtils.broadcast_error(
                data=[SpInterruptionError()],
                # these cells are transitioning from queued to stopped
                # (interrupted); they didn't get to run, so their consoles
                # reflect a previous run and should be cleared
                clear_console=True,
                cell_id=cid,
            )


@kernel_tracer.start_as_current_span("send_cancellation_errors")
def _send_cancellation_errors(ctx: OnFinishHookContext) -> None:
    for raising_cell in ctx.cancelled_cells:
        for cid in ctx.cancelled_cells[raising_cell]:
            # `cid` was not run
            cell = ctx.graph.cells[cid]
            if cell.runtime_state != "idle":
                # the cell raising an exception will already be
                # idle, but its descendants won't be.
                cell.set_runtime_state("idle")

            exception = ctx.exceptions[raising_cell]
            data: Error
            if isinstance(exception, SpStopError):
                data = SpAncestorStoppedError(
                    msg=(
                        "This cell wasn't run because an "
                        "ancestor was stopped with `sp.stop`: "
                    ),
                    raising_cell=raising_cell,
                )
            elif isinstance(exception, SpStrictExecutionError):
                data = SpAncestorPreventedError(
                    msg=(
                        "This cell wasn't run because an "
                        f"ancestor failed to resolve the "
                        f"reference `{exception.ref}` : "
                    ),
                    raising_cell=raising_cell,
                    blamed_cell=exception.blamed_cell,
                )
            else:
                exception_type = type(exception).__name__
                data = SpExceptionRaisedError(
                    msg=(
                        f"An ancestor raised an exception ({exception_type}): "
                    ),
                    exception_type="Ancestor raised",
                    raising_cell=raising_cell,
                )
            CellNotificationUtils.broadcast_error(
                data=[data],
                # these cells are transitioning from queued to stopped
                # (interrupted); they didn't get to run, so their consoles
                # reflect a previous run and should be cleared
                clear_console=True,
                cell_id=cid,
            )


ON_FINISH_HOOKS: list[OnFinishHook] = [
    _send_interrupt_errors,
    _send_cancellation_errors,
]
