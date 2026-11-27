"""Generation cache: one JSON line per generated text.

The file format and the key scheme are those of toolkit/drift/model.py, so a cache written by
the paper's scripts can be reused by `driftaudit run --backend hf`, and the other way round.
An interrupted run resumes from the cache, and environments that share a decoding share text.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Iterable, Optional, Tuple, Union

from ..errors import DriftAuditError


def key(*parts: object) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def generation_key(mock: bool, model: str, system_prompt: str, item_id: str, decoding: str,
                   seed: int, tag: str, max_new_tokens: int) -> str:
    """Cache key for one generation. `decoding` is the key string, e.g. "greedy-0.0".

    Greedy "current" text does not depend on the seed, so it is shared across seeds. A rerun
    always has its own key: it is a second generation and never a copy of the stored one, also
    under greedy decoding, where batching and half-precision rounding can change the text.
    """
    if decoding.startswith("greedy-") and tag != "rerun":
        seed, tag = 0, "greedy"
    return key(mock, model, system_prompt, item_id, decoding, seed, tag, max_new_tokens)


class Cache:
    """Texts by key, held in memory and appended to a JSONL file when a path is given.

    Each row is {"k": key, "v": text} plus "p", the id of the generation pass that produced
    it, so a later run that reuses the text can say which batch layout it came from.
    """

    def __init__(self, path: Union[str, "os.PathLike[str]", None] = None) -> None:
        self.path: Optional[str] = os.fspath(path) if path is not None else None
        self.data: Dict[str, str] = {}
        self.origin: Dict[str, str] = {}
        self.skipped = 0
        self._ends_mid_line = False
        if self.path is not None and os.path.exists(self.path):
            self._load(self.path)

    def _load(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        self._ends_mid_line = bool(lines[-1])
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                k, v = row["k"], row["v"]
                if not isinstance(k, str) or not isinstance(v, str):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                # A process killed while appending leaves a cut-off row behind. Losing that
                # one row is fine; the text is generated again.
                self.skipped += 1
                continue
            self.data[k] = v
            if isinstance(row.get("p"), str):
                self.origin[k] = row["p"]
        if self.skipped and not self.data:
            # Nothing in the file is a cache row, so it is some other file. Refuse before
            # anything gets appended to it.
            raise DriftAuditError(
                f"{path} is not a generation cache (no line has the form "
                '{"k": ..., "v": ...}). Pass a different --cache file.')

    def __len__(self) -> int:
        return len(self.data)

    def get(self, k: str) -> Optional[str]:
        return self.data.get(k)

    def put_many(self, pairs: Iterable[Tuple[str, str]], pass_id: Optional[str] = None) -> None:
        rows = []
        for k, v in pairs:
            self.data[k] = v
            row = {"k": k, "v": v}
            if pass_id is not None:
                self.origin[k] = pass_id
                row["p"] = pass_id
            rows.append(json.dumps(row) + "\n")
        if self.path is None or not rows:
            return
        with open(self.path, "a", encoding="utf-8") as f:
            if self._ends_mid_line:
                f.write("\n")
                self._ends_mid_line = False
            f.write("".join(rows))
