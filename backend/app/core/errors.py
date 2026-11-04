"""Shared API error model (scaffold)."""


class SentinelError(Exception):
    """Base error with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
