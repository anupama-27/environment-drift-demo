"""Errors DriftAudit raises on purpose. Each message says what is wrong and what to do next."""
from __future__ import annotations

from typing import Iterable, Optional


class DriftAuditError(Exception):
    """Base class, so a caller can catch everything the package raises deliberately."""


class RunLogError(DriftAuditError):
    """A run log that cannot be read or does not follow the v1 format.

    problems holds every finding of the validator; the message shows the first few.
    """

    def __init__(self, message: str, problems: Optional[Iterable[str]] = None):
        super().__init__(message)
        self.problems = list(problems or [])


class MissingLabels(DriftAuditError):
    """An analysis needs labels the run log does not contain.

    missing lists them as {"prompt", "env", "pass"}, the same shape an unavailable policy
    reports in an audit.
    """

    def __init__(self, message: str, missing: Optional[Iterable[dict]] = None):
        super().__init__(message)
        self.missing = list(missing or [])
