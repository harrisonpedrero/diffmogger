from __future__ import annotations

import argparse
from typing import Any


class BackendError(Exception):
    def __init__(
        self,
        message: str,
        *,
        exit_code: int = 1,
        error_type: str = "backend_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.error_type = error_type
        self.details = details or {}


class BackendArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        from .jsonio import emit, failure

        error = BackendError(message, exit_code=2, error_type="argument_error")
        command = "unknown"
        emit(failure(command, error))
        raise SystemExit(error.exit_code)
