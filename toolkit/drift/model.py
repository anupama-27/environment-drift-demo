"""Text generation backends plus an on-disk cache.

Every generation is cached by (model, system prompt, item, decoding, seed, tag), so
re-scoring the same text with a different extractor (E1 vs E3) never calls the model
again, and an interrupted Kaggle/A100 session can resume where it stopped.
"""
import hashlib
import json
import os
import random

from . import config


def _key(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()


class Cache:
    def __init__(self, path=config.CACHE_PATH):
        self.path = path
        self.data = {}
        self.origin = {}  # cache key -> id of the generation pass that produced it
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        row = json.loads(line)
                        self.data[row["k"]] = row["v"]
                        if "p" in row:
                            self.origin[row["k"]] = row["p"]

    def get(self, k):
        return self.data.get(k)

    def put_many(self, pairs, pass_id=None):
        """pass_id (optional) is saved with each row, so a later run that reuses the text
        can say which generation pass (and therefore which batch layout) produced it."""
        with open(self.path, "a") as f:
            for k, v in pairs:
                self.data[k] = v
                row = {"k": k, "v": v}
                if pass_id is not None:
                    self.origin[k] = pass_id
                    row["p"] = pass_id
                f.write(json.dumps(row) + "\n")


class BaseGenerator:
    """Subclasses implement _chat(list_of_message_lists, temperature, seeds, max_new_tokens)."""

    def __init__(self):
        self.physical_calls = 0

    def chat(self, conversations, temperature, seeds, max_new_tokens=config.MAX_NEW_TOKENS):
        outs = []
        for i in range(0, len(conversations), config.BATCH_SIZE):
            batch = conversations[i:i + config.BATCH_SIZE]
            outs.extend(self._chat(batch, temperature, seeds[i:i + config.BATCH_SIZE], max_new_tokens))
            self.physical_calls += len(batch)
        return outs


class HFGenerator(BaseGenerator):
    def __init__(self, model_id=config.MODEL_ID):
        super().__init__()
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id, padding_side="left")
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, device_map={"": 0} if torch.cuda.is_available() else None)
        self.model.eval()

    def _chat(self, batch, temperature, seeds, max_new_tokens):
        texts = [self.tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True) for m in batch]
        enc = self.tok(texts, return_tensors="pt", padding=True).to(self.model.device)
        kwargs = dict(max_new_tokens=max_new_tokens, pad_token_id=self.tok.eos_token_id)
        if temperature > 0:
            # HF cannot seed each row separately; seed the batch from its first item.
            self.torch.manual_seed(seeds[0])
            kwargs.update(do_sample=True, temperature=temperature, top_p=1.0)
        else:
            kwargs.update(do_sample=False)
        with self.torch.no_grad():
            out = self.model.generate(**enc, **kwargs)
        new = out[:, enc["input_ids"].shape[1]:]
        return self.tok.batch_decode(new, skip_special_tokens=True)


class VLLMGenerator(BaseGenerator):
    """Much faster on Kaggle T4 (pip install vllm). Seeds are per request."""

    def __init__(self, model_id=config.MODEL_ID):
        super().__init__()
        from vllm import LLM, SamplingParams
        from transformers import AutoTokenizer
        self.SamplingParams = SamplingParams
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.llm = LLM(model=model_id, dtype="half", gpu_memory_utilization=0.85)

    def chat(self, conversations, temperature, seeds, max_new_tokens=config.MAX_NEW_TOKENS):
        texts = [self.tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
                 for m in conversations]
        params = [self.SamplingParams(temperature=temperature, max_tokens=max_new_tokens,
                                      seed=s if temperature > 0 else None) for s in seeds]
        outs = self.llm.generate(texts, params, use_tqdm=False)
        self.physical_calls += len(texts)
        return [o.outputs[0].text for o in outs]


class MockGenerator(BaseGenerator):
    """Fake model for testing the pipeline without a GPU. Not for real numbers.

    Accuracy depends on the prompt, sampling adds noise, and some answers come out in
    \\boxed{} or with commas so that the v2 extractor finds more of them.
    """

    def _chat(self, batch, temperature, seeds, max_new_tokens):
        outs = []
        for msgs, seed in zip(batch, seeds):
            system, user = msgs[0]["content"], msgs[-1]["content"]
            if "improve" in system.lower():  # proposer call
                rnd = random.Random(_key(user, seed))
                tip = rnd.choice(["Check each step.", "Re-read the question.", "Write units.",
                                  "Double-check arithmetic.", "List known values first."])
                outs.append(f"<prompt>{config.INITIAL_PROMPT} {tip} v{rnd.randint(0, 999)}</prompt>")
                continue
            rnd = random.Random(_key(system, user, seed if temperature > 0 else 0))
            nums = [int(t) for t in user.replace("?", " ").split() if t.isdigit()]
            gold = sum(nums)
            skill = 0.45 + (int(_key(system)[:4], 16) % 30) / 100.0
            ans = gold if rnd.random() < skill else gold + rnd.randint(1, 5)
            style = rnd.random()
            if style < 0.15:
                outs.append(f"So the answer is \\boxed{{{ans}}}.")
            elif style < 0.25:
                outs.append(f"Steps...\n#### ${ans}")
            else:
                outs.append(f"Steps...\n#### {ans}")
        return outs


def make_generator():
    if config.BACKEND == "vllm":
        return VLLMGenerator()
    if config.BACKEND == "mock":
        return MockGenerator()
    return HFGenerator()


def generation_key(system_prompt, item_id, env, seed, tag):
    """Cache key for one generation.

    Greedy "current" outputs do not depend on the seed, so they are shared across seeds.
    A "rerun" always gets its own key, so it is a real second generation and never a copy of
    the stored output, even under greedy decoding (GPU batching and fp16 rounding can change
    greedy text between runs). E1 and E3 share decoding, so they share the same rerun text and
    differ only in the extractor applied to it.
    """
    if env.decoding == "greedy" and tag != "rerun":
        seed, tag = 0, "greedy"
    return _key(config.BACKEND == "mock", config.MODEL_ID, system_prompt, item_id, env.decoding_key, seed, tag, config.MAX_NEW_TOKENS)


def item_seed(seed, tag, item_id):
    return int(_key(seed, tag, item_id)[:8], 16)

