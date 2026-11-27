"""What the loop needs from a model."""
from __future__ import annotations

from typing import Dict, List, Sequence

Message = Dict[str, str]
Conversation = List[Message]


class Backend:
    """A chat model behind one method.

    One call to chat() is one batch: the loop decides which items go together and in which
    order, and records that layout in the run log. Subclasses implement _chat().
    """

    name = "base"
    # True for a simulator. Its runs are written as "synthetic", never as "measured".
    synthetic = False

    def __init__(self) -> None:
        # Conversations actually sent to the model by this object (cache hits never get here).
        self.physical_calls = 0

    def chat(self, conversations: Sequence[Conversation], temperature: float,
             seeds: Sequence[int], max_new_tokens: int) -> List[str]:
        """One reply per conversation, in order. `seeds` are used only when temperature > 0."""
        if len(conversations) != len(seeds):
            raise ValueError(f"{len(conversations)} conversations but {len(seeds)} seeds")
        if not conversations:
            return []
        texts = self._chat(list(conversations), float(temperature), list(seeds), int(max_new_tokens))
        if len(texts) != len(conversations):
            raise RuntimeError(f"{self.name} backend returned {len(texts)} replies for "
                               f"{len(conversations)} conversations")
        self.physical_calls += len(conversations)
        return texts

    def _chat(self, conversations: List[Conversation], temperature: float,
              seeds: List[int], max_new_tokens: int) -> List[str]:
        raise NotImplementedError

    def describe(self) -> Dict[str, object]:
        """What identifies the model as served here: at least `backend` and `model`.

        The loop folds this into every environment fingerprint, so a different model,
        revision or serving stack reads as an environment change.
        """
        raise NotImplementedError

    @property
    def cache_id(self) -> str:
        """Model identity inside generation cache keys."""
        return str(self.describe()["model"])

    def versions(self) -> Dict[str, str]:
        """Versions of the libraries that produce the text, for the run log."""
        return {}
