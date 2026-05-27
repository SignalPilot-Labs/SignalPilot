# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations


class SpRuntimeException(BaseException):
    """Wrapper for all sp runtime exceptions."""


class SpNameError(NameError):
    """Wrap a name error to rethrow later."""

    def __init__(self, msg: str, ref: str) -> None:
        super().__init__(msg)
        self.ref = ref


class SpMissingRefError(BaseException):
    def __init__(self, ref: str, name_error: NameError | None = None) -> None:
        super().__init__(ref)
        self.ref = ref
        self.name_error = name_error
