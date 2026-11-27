"""Model backends for the built-in loop, and the generation cache they share."""
from __future__ import annotations

import inspect
from typing import Any

from ..errors import DriftAuditError
from .base import Backend
from .cache import Cache

BACKENDS = ("mock", "hf", "openai")


def make_backend(name: str, **options: Any) -> Backend:
    """Create a backend by name.

    mock    items=...  the task items; it simulates answers from their gold answers
    hf      model=...  a Hugging Face model id; needs the [hf] extra
    openai  model=..., base_url=..., concurrency=..., timeout=...  any OpenAI-compatible server

    Each backend module is imported only when it is asked for, so torch is never loaded by
    accident.
    """
    if name == "mock":
        from .mock import MockBackend as backend
    elif name == "hf":
        from .hf import HFBackend as backend
    elif name in ("openai", "openai_compat"):
        from .openai_compat import OpenAICompatBackend as backend
    else:
        raise DriftAuditError(f"Unknown backend {name!r}. Choose one of: {', '.join(BACKENDS)}.")
    try:
        inspect.signature(backend).bind(**options)
    except TypeError as exc:
        raise DriftAuditError(f"Cannot create the {name} backend: {exc}.") from None
    return backend(**options)


__all__ = ["BACKENDS", "Backend", "Cache", "make_backend"]
