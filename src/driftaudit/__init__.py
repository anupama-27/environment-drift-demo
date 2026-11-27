"""DriftAudit: audit stale references in self-improving LLM loops.

A reference in a self-improvement loop is a measurement tied to an environment version
(decoding settings, answer extractor, model). DriftAudit records that version with every
reference, compares each candidate against the stored and the rerun reference, and replays
refresh policies on the same candidates.

    import driftaudit as da

    run = da.load("run.json")
    result = da.audit(run)
    print(result["policies"]["frozen"]["false_accepts"])
"""
from __future__ import annotations

from importlib import import_module

__version__ = "0.1.0"

# Public name -> module that defines it. Resolved on first access so that importing
# driftaudit stays cheap and the optional backends are never imported by accident.
_EXPORTS = {
    "load": "schema",
    "save": "schema",
    "validate": "schema",
    "upgrade_legacy": "schema",
    "Environment": "envs",
    "audit": "engine",
    "study": "engine",
    "simulate": "engine",
    "POLICIES": "engine",
    "Scorer": "scoring",
    "get_scorer": "scoring",
    "Recorder": "recorder",
    "ReferenceStore": "recorder",
    "run_loop": "loop",
    "DriftAuditError": "errors",
    "RunLogError": "errors",
    "MissingLabels": "errors",
}

__all__ = ["__version__", *sorted(_EXPORTS)]


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'driftaudit' has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__)
