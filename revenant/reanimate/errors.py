"""The single failure type of the Reanimate Runner."""

from __future__ import annotations


class ReanimateError(Exception):
    """A Runner stage failed; `code` is the process exit code (1 or 2)."""

    def __init__(self, stage: str, message: str, code: int = 1) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message
        self.code = code
