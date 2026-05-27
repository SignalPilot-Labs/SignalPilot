# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

from signalpilot._output.rich_help import mddoc

# We used to define a custom SpInterrupt BaseException to interrupt the
# kernel; however, some third-party libraries like databricks-connect have
# special case handling of KeyboardInterrupt.
SpInterrupt = KeyboardInterrupt


class SpStopError(BaseException):
    """Raised by `sp.stop` to stop execution of a cell and descendants.

    Inherits from `BaseException` to prevent accidental capture with
    `except Exception` (similar to `KeyboardInterrupt`)

    Args:
        output: optional output object
    """

    def __init__(self, output: object | None) -> None:
        self.output = output


@mddoc
def stop(predicate: bool, output: object | None = None) -> None:
    """Stops execution of a cell when `predicate` is `True`

    When `predicate` is `True`, this function raises a `SpStopError`. If
    uncaught, this exception stops execution of the current cell and makes
    `output` its output. Any descendants of this cell that were previously
    scheduled to run will not be run, and their defs will be removed from
    program memory.

    Examples:
        ```python
        sp.stop(form.value is None, sp.md("**Submit the form to continue.**"))
        ```

    Args:
        predicate (bool): The predicate indicating whether to stop.
        output (bool): The output to be assigned to the current cell.

    Raises:
        SpStopError: When `predicate` is `True`
    """
    if predicate:
        raise SpStopError(output)
