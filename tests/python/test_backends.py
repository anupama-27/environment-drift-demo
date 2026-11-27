"""Backends and the generation cache. Nothing here leaves the machine or needs a GPU."""
from __future__ import annotations

import json
import os
import sys

import pytest

from app_fixtures import stub_chat  # noqa: F401
from driftaudit import schema
from driftaudit.backends import Cache, make_backend
from driftaudit.backends import mock
from driftaudit.backends.openai_compat import OpenAICompatBackend
from driftaudit.errors import DriftAuditError
from driftaudit.loop import parse_candidate, proposer_messages, run_loop, write_outputs
from driftaudit.scoring import get_scorer
from driftaudit.tasks import load_task

KEY = "sk-test-0123456789abcdef"
SYSTEM = "You are a careful math tutor. Solve it. Put the number in \\boxed{}."


def chat(question="What is 2 + 2?"):
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("DRIFTAUDIT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_make_backend_names_its_choices():
    with pytest.raises(DriftAuditError, match="mock, hf, openai"):
        make_backend("llamacpp")
    with pytest.raises(DriftAuditError, match="missing a required argument: 'items'"):
        make_backend("mock")
    with pytest.raises(DriftAuditError, match="unexpected keyword argument 'temperature'"):
        make_backend("openai", model="m", temperature=1)


def test_cache_keeps_text_and_the_pass_it_came_from(tmp_path):
    path = tmp_path / "gen.jsonl"
    cache = Cache(path)
    cache.put_many([("k1", "one"), ("k2", "two \\boxed{2}\n")], pass_id="s1-pass-0")
    cache.put_many([("k3", "three")])
    again = Cache(path)
    assert (again.get("k1"), again.get("k2"), again.get("k3"), again.get("k4")) == ("one", "two \\boxed{2}\n", "three", None)
    assert again.origin == {"k1": "s1-pass-0", "k2": "s1-pass-0"} and len(again) == 3
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0]) == {"k": "k1", "v": "one", "p": "s1-pass-0"}
    memory = Cache()
    memory.put_many([("k", "v")])
    assert memory.get("k") == "v" and memory.path is None


def test_cache_survives_a_row_cut_off_mid_write(tmp_path):
    path = tmp_path / "gen.jsonl"
    Cache(path).put_many([("k1", "one"), ("k2", "two")])
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"k": "k3", "v": "thr')
    cache = Cache(path)
    assert cache.get("k2") == "two" and cache.get("k3") is None and cache.skipped == 1
    cache.put_many([("k4", "four")])
    reloaded = Cache(path)
    assert reloaded.get("k4") == "four" and reloaded.get("k1") == "one" and reloaded.skipped == 1


def test_cache_refuses_a_file_that_is_something_else(tmp_path):
    path = tmp_path / "run.json"
    path.write_text('{"schema": "driftaudit.run/v1"}\n', encoding="utf-8")
    with pytest.raises(DriftAuditError, match="not a generation cache"):
        Cache(path)
    assert path.read_text(encoding="utf-8") == '{"schema": "driftaudit.run/v1"}\n'


@pytest.fixture(scope="module")
def simulator():
    task = load_task("gsm8k", 20, 200)
    return make_backend("mock", items=task.dev + task.eval), task


def test_mock_is_a_pure_function_of_its_arguments(simulator):
    backend, task = simulator
    convs = [chat(item["question"]) for item in task.eval[:50]]
    seeds = list(range(50))
    greedy = backend.chat(convs, 0.0, seeds, 64)
    assert backend.chat(convs, 0.0, [s + 99 for s in seeds], 64) == greedy
    sampled = backend.chat(convs, 0.2, seeds, 64)
    assert backend.chat(convs, 0.2, seeds, 64) == sampled
    assert backend.chat(convs, 0.2, [s + 99 for s in seeds], 64) != sampled
    assert sampled != greedy and backend.describe() == {"backend": "mock", "model": "driftaudit-mock", "revision": "2"}
    assert backend.synthetic and backend.cache_id == "driftaudit-mock@2"
    assert "import random" not in open(mock.__file__, encoding="utf-8").read()


def test_mock_accuracy_depends_on_the_instruction_and_formats_vary(simulator):
    backend, task = simulator
    strict, lenient = get_scorer("strict"), get_scorer("lenient")
    accuracy = {}
    for system in (SYSTEM, "Answer fast.", "Include units such as dollars with the answer."):
        texts = backend.chat([[{"role": "system", "content": system}, {"role": "user", "content": i["question"]}]
                              for i in task.eval], 0.0, [0] * 200, 64)
        right = [(strict.correct(strict.extract(t), i["gold"]), lenient.correct(lenient.extract(t), i["gold"]))
                 for t, i in zip(texts, task.eval)]
        assert all(l or not s for s, l in right)
        accuracy[system] = (sum(s for s, _ in right), sum(l for _, l in right))
    assert len(set(accuracy.values())) == 3
    assert all(90 < lenient_right < 180 for _, lenient_right in accuracy.values())
    plain, units = accuracy[SYSTEM], accuracy["Include units such as dollars with the answer."]
    assert 0 < plain[1] - plain[0] < 10 < units[1] - units[0]


@pytest.mark.parametrize("value", [72.0, 1250.0, 12.5, -3.0, 0.0])
def test_only_the_plain_format_is_read_by_the_strict_scorer(value):
    strict, lenient = get_scorer("strict"), get_scorer("lenient")
    assert strict.extract("Work it out.\n" + mock.format_answer(value, "plain")) == value
    for style in mock._loose_styles(value):
        text = "Work it out.\n" + mock.format_answer(value, style)
        assert strict.extract(text) is None and lenient.extract(text) == value, style
    assert set(mock._loose_styles(1250.0)) == set(mock.STYLES) - {"plain"}
    assert "dollar" not in mock._loose_styles(-3.0) and "commas" not in mock._loose_styles(72.0)


def test_mock_proposer_returns_a_usable_instruction(simulator):
    backend, task = simulator
    failures = [{"question": i["question"], "output": "\\boxed{1}", "gold": i["gold"]} for i in task.dev[:4]]
    notes = set()
    for seed in range(60):
        reply = backend.chat([proposer_messages(SYSTEM, failures, "You improve instructions.")], 0.7, [seed], 64)[0]
        candidate, note = parse_candidate(reply, SYSTEM, "Put the final answer as a plain number in \\boxed{} on the last line.")
        notes.add(note)
        if note != "fallback_unparsed":
            assert candidate.startswith("You are a careful math tutor. ") and "boxed" in candidate and candidate != SYSTEM
    assert notes == {"ok", "format_line_added", "fallback_unparsed"}


def test_mock_answers_text_tasks_for_exact_match():
    items = [{"id": str(i), "question": f"Capital {i}?", "gold": f"City {i}"} for i in range(120)]
    backend = make_backend("mock", items=items)
    # An instruction that asks for units is the simulator's cue for loosely formatted answers.
    convs = [[{"role": "system", "content": "Answer and include units."}, {"role": "user", "content": i["question"]}]
             for i in items]
    texts = backend.chat(convs, 0.0, [0] * 120, 16)
    exact, normalized = get_scorer("exact"), get_scorer("exact-normalized")
    e = sum(exact.correct(exact.extract(t), i["gold"]) for t, i in zip(texts, items))
    n = sum(normalized.correct(normalized.extract(t), i["gold"]) for t, i in zip(texts, items))
    assert 0 < e < n < 120
    with pytest.raises(DriftAuditError, match="needs the task items"):
        make_backend("mock", items=[])


def test_openai_request_carries_model_messages_and_limits(stub_chat, monkeypatch, no_key):
    monkeypatch.setenv("DRIFTAUDIT_API_KEY", KEY)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-other-one")
    stub = stub_chat()
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url + "/chat/completions/", concurrency=1)
    assert backend.chat([chat()], 0.0, [5], 32) == ["\\boxed{14}"]
    assert backend.chat([chat()], 0.2, [5], 32) == ["\\boxed{14}"]
    (path, headers, greedy), (_, _, sampled) = stub.requests
    assert path == "/v1/chat/completions" and headers["Authorization"] == f"Bearer {KEY}"
    assert greedy == {"model": "tiny", "messages": chat(), "temperature": 0.0, "max_tokens": 32}
    assert sampled == dict(greedy, temperature=0.2, seed=5)
    assert backend.physical_calls == 2 and backend.cache_id == f"tiny@{stub.base_url}"
    assert backend.describe() == {"backend": "openai", "model": "tiny", "base_url": stub.base_url,
                                  "served_model": "tiny-2026-01", "system_fingerprint": "fp_stub"}
    assert KEY not in repr(backend.describe()) and KEY not in repr(vars(backend).keys())


def test_openai_works_without_a_key(stub_chat, no_key):
    stub = stub_chat(fingerprint=None)
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url)
    assert backend.chat([chat()], 0.0, [1], 8) == ["\\boxed{14}"]
    assert "Authorization" not in stub.requests[0][1] and "system_fingerprint" not in backend.describe()
    assert OpenAICompatBackend("gpt-x").cache_id == "gpt-x"


def test_openai_retries_server_errors_then_succeeds(stub_chat, no_key):
    stub = stub_chat(plan=[500, 429, 503])
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url, backoff=0.01)
    assert backend.chat([chat()], 0.0, [1], 8) == ["\\boxed{14}"]
    assert len(stub.requests) == 4 and backend.physical_calls == 1


def test_openai_gives_up_after_bounded_retries(stub_chat, no_key):
    stub = stub_chat(plan=[500] * 10)
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url, backoff=0.01, max_retries=2)
    with pytest.raises(DriftAuditError, match=r"no usable answer in 3 attempts \(HTTP 500: stub says 500\)"):
        backend.chat([chat()], 0.0, [1], 8)
    assert len(stub.requests) == 3 and backend.physical_calls == 0


def test_openai_does_not_retry_what_retrying_cannot_fix(stub_chat, monkeypatch, no_key):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    for status, hint in ((400, "rejected the request \\(HTTP 400\\): stub says 400"), (404, "usually ends in /v1"),
                         (401, "refused the credentials"), (302, "redirects elsewhere")):
        stub = stub_chat(plan=[status])
        backend = OpenAICompatBackend("tiny", base_url=stub.base_url, backoff=0.01)
        with pytest.raises(DriftAuditError, match=hint) as caught:
            backend.chat([chat()], 0.0, [1], 8)
        assert len(stub.requests) == 1 and KEY not in str(caught.value)


def test_openai_reports_a_server_that_is_not_there_or_not_compatible(stub_chat, no_key):
    stub = stub_chat()
    dead = stub.base_url
    stub.shutdown()
    stub.server_close()
    with pytest.raises(DriftAuditError, match="Check that the server is running"):
        OpenAICompatBackend("tiny", base_url=dead, backoff=0.01, max_retries=1).chat([chat()], 0.0, [1], 8)
    odd = stub_chat(reply=lambda body: None)
    assert OpenAICompatBackend("tiny", base_url=odd.base_url).chat([chat()], 0.0, [1], 8) == [""]


def test_openai_keeps_order_under_concurrency_and_skips_proxies_for_localhost(stub_chat, monkeypatch, no_key):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    stub = stub_chat(reply=lambda body: body["messages"][-1]["content"].upper())
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url, concurrency=8)
    questions = [f"question {i}" for i in range(40)]
    assert backend.chat([chat(q) for q in questions], 0.2, list(range(40)), 8) == [q.upper() for q in questions]
    assert sorted(body["seed"] for _, _, body in stub.requests) == list(range(40))


def test_openai_stops_the_batch_at_the_first_fatal_error(stub_chat, no_key):
    stub = stub_chat(plan=[400] * 100)
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url, concurrency=4)
    with pytest.raises(DriftAuditError, match="HTTP 400"):
        backend.chat([chat(f"q{i}") for i in range(64)], 0.0, [0] * 64, 8)
    assert len(stub.requests) < 64


@pytest.mark.parametrize("url", ["ftp://host/v1", "localhost:11434/v1", "http://", "https://user:pw@host/v1",
                                 "https://host/v1?key=abc", "file:///etc/passwd"])
def test_openai_base_url_must_be_plain_http(url, no_key):
    with pytest.raises(DriftAuditError, match="--base-url"):
        OpenAICompatBackend("tiny", base_url=url)
    with pytest.raises(DriftAuditError, match="needs a model name"):
        OpenAICompatBackend("")


def test_api_key_is_in_no_file_a_run_writes(stub_chat, monkeypatch, no_key, tmp_path):
    monkeypatch.setenv("DRIFTAUDIT_API_KEY", KEY)
    task = load_task("gsm8k", 4, 6)
    gold = {item["question"]: item["gold"] for item in task.dev + task.eval}

    def reply(body):
        question = body["messages"][-1]["content"]
        if question in gold:
            return f"\\boxed{{{int(gold[question]) + len(body['messages'][0]['content']) % 2}}}"
        return "<prompt>You are a careful math tutor. Check every step twice before answering.</prompt>"

    stub = stub_chat(reply=reply)
    backend = make_backend("openai", model="tiny", base_url=stub.base_url, concurrency=4)
    run, outputs = run_loop(task, backend, schedule="0:greedy/strict,1:sample@0.2/lenient", rounds=2,
                            cache_path=tmp_path / "cache.jsonl")
    write_outputs(tmp_path / "run.outputs.jsonl", outputs)
    schema.save(run, tmp_path / "run.json")
    assert all(headers["Authorization"] == f"Bearer {KEY}" for _, headers, _ in stub.requests)
    for name in sorted(os.listdir(tmp_path)):
        assert KEY not in (tmp_path / name).read_text(encoding="utf-8"), name
    assert run["source"] == "measured" and run["model"]["system_fingerprint"] == "fp_stub"
    assert run["environments"]["E1"]["fingerprint"] == (
        f"model=tiny;decode=greedy-0.0;extract=strict@1;backend=openai;base_url={stub.base_url};"
        "served_model=tiny-2026-01;system_fingerprint=fp_stub")
    assert "python" in run["meta"]["software"] and "created" in run


def test_hf_backend_says_how_to_install_what_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(DriftAuditError, match=r'torch is not installed\. Run: pip install "driftaudit\[hf\] @ git\+https://github\.com/anupama-27/'
                       r'environment-drift-demo", or pip install -e "\.\[hf\]" from a clone'):
        make_backend("hf")
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(DriftAuditError, match=r'pip install "driftaudit\[hf\] @ git\+'):
        make_backend("hf", model="some/model")


def test_hf_backend_runs_a_tiny_local_model(tmp_path):
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    words = ["<pad>", "<eos>", "<unk>", "system", "user", "assistant", ":", "add", "the", "numbers",
             "what", "is", "one", "plus", "two", "three", "five", "?"]
    tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({w: i for i, w in enumerate(words)}, unk_token="<unk>"))
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.WhitespaceSplit()
    fast = transformers.PreTrainedTokenizerFast(tokenizer_object=tokenizer, pad_token="<pad>", eos_token="<eos>",
                                                unk_token="<unk>")
    fast.chat_template = ("{% for m in messages %}{{ m['role'] }} : {{ m['content'] }} {% endfor %}"
                          "{% if add_generation_prompt %}assistant : {% endif %}")
    fast.save_pretrained(str(tmp_path))
    torch.manual_seed(0)
    config = transformers.GPT2Config(vocab_size=len(words), n_positions=64, n_embd=16, n_layer=1, n_head=2,
                                     bos_token_id=1, eos_token_id=1, pad_token_id=0)
    transformers.GPT2LMHeadModel(config).save_pretrained(str(tmp_path))

    backend = make_backend("hf", model=str(tmp_path))
    convs = [[{"role": "system", "content": "add the numbers"}, {"role": "user", "content": question}]
             for question in ("what is one plus two ?", "what is three plus five ?", "what is one ?")]
    greedy = backend.chat(convs, 0.0, [1, 2, 3], 6)
    assert len(greedy) == 3 and all(isinstance(text, str) for text in greedy)
    assert backend.chat(convs, 0.0, [7, 8, 9], 6) == greedy
    sampled = backend.chat(convs, 1.5, [4, 5, 6], 6)
    assert backend.chat(convs, 1.5, [4, 5, 6], 6) == sampled
    assert backend.physical_calls == 12
    info = backend.describe()
    assert (info["backend"], info["model"]) == ("hf", str(tmp_path)) and info["device"] in ("cpu", "cuda", "mps")
    assert info["dtype"] == ("float16" if info["device"] == "cuda" else "float32")
    assert set(backend.versions()) == {"torch", "transformers"}


def test_openai_key_goes_to_openai_only_and_the_own_key_to_any_endpoint(stub_chat, monkeypatch, no_key):
    from driftaudit.backends import openai_compat
    monkeypatch.setenv("OPENAI_API_KEY", "sk-for-openai")
    stub = stub_chat()
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url)
    backend.chat([chat()], 0.0, [1], 8)
    assert "Authorization" not in stub.requests[0][1] and backend.key_variable is None
    assert openai_compat._key_from_environment("api.openai.com") == ("sk-for-openai", "OPENAI_API_KEY")
    monkeypatch.setenv("DRIFTAUDIT_API_KEY", KEY)
    backend = OpenAICompatBackend("tiny", base_url=stub.base_url)
    backend.chat([chat()], 0.0, [1], 8)
    assert stub.requests[1][1]["Authorization"] == f"Bearer {KEY}" and backend.key_variable == "DRIFTAUDIT_API_KEY"
    assert openai_compat._key_from_environment("api.openai.com") == (KEY, "DRIFTAUDIT_API_KEY")


@pytest.mark.parametrize("url", ["http://127.0.0.2:8000/v1", "http://gpu-box:8000/v1", "http://10.0.0.5/v1"])
def test_openai_refuses_plain_http_off_this_machine_unless_allowed(url, no_key):
    with pytest.raises(DriftAuditError, match="plain http to another machine.*--allow-insecure-http"):
        OpenAICompatBackend("tiny", base_url=url)
    assert OpenAICompatBackend("tiny", base_url=url, allow_insecure_http=True).base_url == url
    for local in ("http://localhost:11434/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"):
        OpenAICompatBackend("tiny", base_url=local)


def test_openai_does_not_follow_a_redirect_with_the_key(stub_chat, monkeypatch, no_key):
    import http.server
    from app_fixtures import serving
    monkeypatch.setenv("DRIFTAUDIT_API_KEY", KEY)
    target = stub_chat()

    class Redirect(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.send_response(307)
            self.send_header("Location", target.base_url.replace("127.0.0.1", "localhost") + "/chat/completions")
            self.send_header("Content-Length", "0")
            self.end_headers()

    with serving(http.server.HTTPServer(("127.0.0.1", 0), Redirect)) as server:
        backend = OpenAICompatBackend("tiny", base_url=f"http://127.0.0.1:{server.server_address[1]}/v1")
        with pytest.raises(DriftAuditError, match="redirects elsewhere"):
            backend.chat([chat()], 0.0, [1], 8)
    assert target.requests == []


def test_openai_caps_the_reply_it_reads(stub_chat, monkeypatch, no_key):
    from driftaudit.backends import openai_compat
    monkeypatch.setattr(openai_compat, "MAX_RESPONSE_BYTES", 64)
    stub = stub_chat(reply=lambda body: "x" * 200)
    with pytest.raises(DriftAuditError, match="larger than"):
        OpenAICompatBackend("tiny", base_url=stub.base_url, max_retries=0).chat([chat()], 0.0, [1], 8)
