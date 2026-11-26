"""Environment versions E1-E4 (the conditions in Table 4)."""
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Env:
    env_id: str
    name: str
    decoding: str        # "greedy" or "sample"
    temperature: float
    extractor: str       # "v1" (strict) or "v2" (also boxed / comma answers)

    @property
    def decoding_key(self):
        return f"{self.decoding}-{self.temperature}"

    @property
    def fingerprint(self):
        """Config string a deployment can read from its own settings, with no access to the schedule.

        This is the signal P3 refreshes on. The model id and revision are fixed for the whole
        experiment, so only the two components that actually vary appear here.
        """
        return f"model={config.MODEL_ID};decode={self.decoding_key};extract={self.extractor}"


ENVS = {
    "E1": Env("E1", "Unchanged environment", "greedy", 0.0, "v1"),
    "E2": Env("E2", "Decoding change", "sample", 0.2, "v1"),
    "E3": Env("E3", "Answer-extraction change", "greedy", 0.0, "v2"),
    "E4": Env("E4", "Multiple environment changes", "sample", 0.2, "v2"),
}


def env_at(round_idx, schedule):
    """Environment id in force at a given round under a schedule {start_round: env_id}."""
    current = schedule[min(schedule)]
    for start in sorted(schedule):
        if round_idx >= start:
            current = schedule[start]
    return current


def map_schedule(schedule, mapping):
    """Used by ablations, e.g. {"E2": "E1", "E4": "E3"} removes the decoding change."""
    return {r: mapping.get(e, e) for r, e in schedule.items()}


