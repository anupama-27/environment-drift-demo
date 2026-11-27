"""A Hugging Face causal language model on this machine. Needs the [hf] extra.

This is the generator the paper's runs used (toolkit/drift/model.py, HFGenerator) with the
model id as a parameter. torch and transformers are imported when the backend is created, so
the rest of the package works without them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..errors import DriftAuditError
from .base import Backend, Conversation

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
# The package is not on PyPI, so the extra is installed from the repository.
INSTALL_HINT = ('pip install "driftaudit[hf] @ git+https://github.com/anupama-27/environment-drift-demo", '
                'or pip install -e ".[hf]" from a clone')


class HFBackend(Backend):
    name = "hf"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        try:
            import torch
            import transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise DriftAuditError(
                f"The hf backend needs torch and transformers, and {exc.name or 'one of them'} "
                f"is not installed. Run: {INSTALL_HINT}") from exc
        self.model_id = model
        self._torch = torch
        self._versions = {"torch": str(torch.__version__), "transformers": str(transformers.__version__)}
        mps = getattr(torch.backends, "mps", None)
        if torch.cuda.is_available():
            # Half precision on a CUDA GPU, as in the paper's runs.
            self.device, self.dtype = "cuda", "float16"
        elif mps is not None and mps.is_available():
            self.device, self.dtype = "mps", "float32"
        else:
            self.device, self.dtype = "cpu", "float32"
        dtype = getattr(torch, self.dtype)
        try:
            # Code shipped inside a model repository is never executed.
            self._tok = AutoTokenizer.from_pretrained(model, padding_side="left", trust_remote_code=False)
            try:
                self._model = AutoModelForCausalLM.from_pretrained(model, dtype=dtype, trust_remote_code=False)
            except TypeError:
                # transformers 4.x knows the argument as torch_dtype.
                self._model = AutoModelForCausalLM.from_pretrained(model, torch_dtype=dtype, trust_remote_code=False)
        except (OSError, ValueError) as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            raise DriftAuditError(f"Could not load the model {model!r}: {first_line}") from exc
        self._model.to(self.device)
        self._model.eval()
        self.revision: Optional[str] = getattr(self._model.config, "_commit_hash", None)

    def describe(self) -> Dict[str, object]:
        info: Dict[str, object] = {"backend": self.name, "model": self.model_id,
                                   "dtype": self.dtype, "device": self.device}
        if self.revision:
            info["revision"] = self.revision
        return info

    def versions(self) -> Dict[str, str]:
        return dict(self._versions)

    def _chat(self, conversations: List[Conversation], temperature: float,
              seeds: List[int], max_new_tokens: int) -> List[str]:
        torch = self._torch
        texts = [self._tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                 for messages in conversations]
        enc = self._tok(texts, return_tensors="pt", padding=True).to(self._model.device)
        kwargs = dict(max_new_tokens=max_new_tokens, pad_token_id=self._tok.eos_token_id)
        if temperature > 0:
            # generate() cannot seed each row separately; seed the batch from its first item.
            torch.manual_seed(seeds[0])
            kwargs.update(do_sample=True, temperature=temperature, top_p=1.0)
        else:
            kwargs.update(do_sample=False)
        with torch.no_grad():
            out = self._model.generate(**enc, **kwargs)
        new = out[:, enc["input_ids"].shape[1]:]
        return self._tok.batch_decode(new, skip_special_tokens=True)
