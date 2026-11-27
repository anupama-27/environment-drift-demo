"""Fixtures for the application layer: a small simulated run, servers on free ports."""
from __future__ import annotations

import contextlib
import http.server
import json
import threading

import pytest

from conftest import paper_run_path

SMALL_SCHEDULE = "0:greedy/strict,2:sample@0.2/strict,4:sample@0.2/lenient"
PAPER_SEED5 = paper_run_path(5)


def small_loop(seed=1, rounds=6, n_dev=30, n_eval=40, schedule=SMALL_SCHEDULE, **options):
    """Run the built-in loop on the mock backend at a size that takes well under a second."""
    from driftaudit.backends import make_backend
    from driftaudit.loop import run_loop
    from driftaudit.tasks import load_task
    task = load_task("gsm8k", n_dev, n_eval)
    backend = make_backend("mock", items=task.dev + task.eval)
    return run_loop(task, backend, schedule=schedule, rounds=rounds, seed=seed, **options)


@pytest.fixture(scope="session")
def mock_loop():
    """(run, outputs) of one small simulated run, shared by the tests that only read it."""
    return small_loop()


@pytest.fixture
def mock_run_file(mock_loop, tmp_path):
    """The small run saved the way `driftaudit run` saves it: run log plus outputs sidecar."""
    from driftaudit import schema
    from driftaudit.loop import write_outputs
    run, outputs = mock_loop
    path = tmp_path / "small.json"
    write_outputs(tmp_path / "small.outputs.jsonl.gz", outputs)
    schema.save(dict(run, outputs={"layout": "sidecar", "file": "small.outputs.jsonl.gz"}), path)
    return path


@contextlib.contextmanager
def serving(server):
    """Serve in a background thread for the length of a with block."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class StubChat(http.server.ThreadingHTTPServer):
    """A local stand-in for an OpenAI-compatible endpoint.

    `plan` is a list of statuses to answer with before the first 200, for example [500, 429].
    Every request is kept in `requests` as (path, headers, body).
    """

    def __init__(self, plan=(), reply=None, fingerprint="fp_stub"):
        super().__init__(("127.0.0.1", 0), _StubHandler)
        self.plan = list(plan)
        self.reply = reply or (lambda body: "\\boxed{" + str(len(body["messages"][-1]["content"])) + "}")
        self.fingerprint = fingerprint
        self.requests = []
        self.lock = threading.Lock()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


class _StubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with self.server.lock:
            self.server.requests.append((self.path, dict(self.headers), body))
            status = self.server.plan.pop(0) if self.server.plan else 200
        if status == 200:
            payload = {"model": body["model"] + "-2026-01", "choices": [
                {"message": {"role": "assistant", "content": self.server.reply(body)}}]}
            if self.server.fingerprint:
                payload["system_fingerprint"] = self.server.fingerprint
        else:
            payload = {"error": {"message": f"stub says {status}"}}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def stub_chat():
    """Factory for stub endpoints that are shut down when the test ends."""
    with contextlib.ExitStack() as stack:
        def start(**options):
            return stack.enter_context(serving(StubChat(**options)))
        yield start
