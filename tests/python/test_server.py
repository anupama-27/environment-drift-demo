"""The local server: what it serves, and what it must never serve."""
from __future__ import annotations

import gzip
import http.client
import json
import os

import pytest

from app_fixtures import PAPER_SEED5, mock_loop, mock_run_file, serving  # noqa: F401
from conftest import ROOT
from driftaudit import schema, server
from driftaudit.errors import DriftAuditError


def fetch(srv, path, method="GET", host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    try:
        conn.putrequest(method, path, skip_host=host is not None)
        if host is not None:
            conn.putheader("Host", host)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def demo():
    with serving(server.make_server(port=0)) as srv:
        yield srv


def test_root_serves_the_workbench_page(demo):
    status, headers, body = fetch(demo, "/")
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert body == open(os.path.join(ROOT, "index.html"), "rb").read()
    assert fetch(demo, "/index.html?session=1")[2] == body


def test_responses_are_never_cached_or_sniffed(demo):
    for path in ("/", "/replay/seed5.json", "/nothing-here"):
        headers = fetch(demo, path)[1]
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["Content-Security-Policy"] == (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def test_head_gives_the_headers_without_the_body(demo):
    status, headers, body = fetch(demo, "/replay/seed5.json", method="HEAD")
    assert status == 200 and body == b""
    assert int(headers["Content-Length"]) == os.path.getsize(os.path.join(ROOT, "replay", "seed5.json"))
    assert headers["Content-Type"] == "application/json; charset=utf-8"


def test_site_files_come_with_fixed_content_types(demo):
    assert fetch(demo, "/favicon.svg")[1]["Content-Type"] == "image/svg+xml"
    assert fetch(demo, "/assets/fonts/barlow-latin-400-normal.woff2")[1]["Content-Type"] == "font/woff2"
    assert fetch(demo, "/data/tasks/gsm8k/eval200.jsonl")[0] == 200
    assert fetch(demo, "/data/index.json")[0] == 200


def test_gzip_files_are_sent_as_they_are(demo):
    folder = os.path.join(ROOT, "data", "outputs", "paper", "shared")
    prompt = sorted(os.listdir(folder))[0]
    name = sorted(n for n in os.listdir(os.path.join(folder, prompt)) if n.endswith(".gz"))[0]
    status, headers, body = fetch(demo, f"/data/outputs/paper/shared/{prompt}/{name}")
    assert status == 200 and headers["Content-Type"] == "application/gzip"
    assert "Content-Encoding" not in headers
    assert len(json.loads(gzip.decompress(body))) == 200


@pytest.mark.parametrize("path", [
    "/../pyproject.toml", "/%2e%2e/pyproject.toml", "/..%2fpyproject.toml", "/%2E%2E%2Fpyproject.toml",
    "/assets/../pyproject.toml", "/assets/%2e%2e/pyproject.toml", "/assets/..%2f..%2fpyproject.toml",
    "/assets/..%5c..%5cpyproject.toml", "/assets/%252e%252e/pyproject.toml", "/replay/..%00/pyproject.toml",
    "//pyproject.toml", "/replay//seed5.json", "/./index.html"])
def test_paths_that_climb_out_are_not_found(demo, path):
    status, _, body = fetch(demo, path)
    assert status == 404 and b"driftaudit" not in body.lower()


@pytest.mark.parametrize("path", [
    "/pyproject.toml", "/README.md", "/src/driftaudit/cli.py", "/.git/HEAD", "/.gitignore",
    "/toolkit/runs/run_seed1_hf_Qwen2.5-1.5B-Instruct_n200_r11.json", "/tests/python/conftest.py"])
def test_only_the_site_is_served_from_a_checkout(demo, path):
    assert os.path.exists(os.path.join(ROOT, path.lstrip("/")))
    assert fetch(demo, path)[0] == 404


@pytest.mark.parametrize("path", ["/assets", "/assets/", "/assets/fonts/", "/data/runs/paper/", "/replay"])
def test_folders_are_not_listed(demo, path):
    assert fetch(demo, path)[0] == 404


def test_other_methods_are_refused(demo):
    assert fetch(demo, "/", method="POST")[0] == 501
    assert fetch(demo, "/index.html", method="DELETE")[0] == 501


def test_requests_under_another_host_name_are_refused(demo):
    assert fetch(demo, "/", host="attacker.example")[0] == 403
    assert fetch(demo, "/", host="attacker.example:8765")[0] == 403
    assert fetch(demo, "/", host="localhost:8765")[0] == 200
    assert fetch(demo, "/", host="[::1]:8765")[0] == 200


def test_no_session_without_run_paths(demo):
    assert fetch(demo, "/session/index.json")[0] == 404
    assert server.server_url(demo) == f"http://127.0.0.1:{demo.server_address[1]}/"


def test_symlink_out_of_the_site_is_not_followed(tmp_path):
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    try:
        os.symlink(secret, site / "assets" / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    (site / "assets" / "ok.txt").write_text("fine", encoding="utf-8")
    with serving(server.make_server(port=0, web=site)) as srv:
        assert fetch(srv, "/assets/ok.txt")[2] == b"fine"
        assert fetch(srv, "/assets/link.txt")[0] == 404


def test_session_serves_the_named_runs_upgraded_to_v1(mock_run_file):
    with serving(server.make_server([PAPER_SEED5, mock_run_file], port=0, title="Two runs")) as srv:
        assert server.server_url(srv).endswith("/?session=1")
        index = json.loads(fetch(srv, "/session/index.json")[2])
        assert index == {"title": "Two runs", "runs": [
            {"name": os.path.basename(PAPER_SEED5), "url": "session/runs/0.json", "outputs": None},
            {"name": "small.json", "url": "session/runs/1.json", "outputs": "session/runs/1.outputs.jsonl.gz"}]}
        status, headers, body = fetch(srv, "/session/runs/0.json")
        legacy = json.loads(body)
        assert status == 200 and headers["Content-Type"] == "application/json; charset=utf-8"
        assert legacy["schema"] == schema.SCHEMA and legacy["id"] == "gsm8k-qwen2.5-1.5b-seed5"
        assert "outputs" not in legacy and schema.validate(legacy) == []
        mine = json.loads(fetch(srv, "/session/runs/1.json")[2])
        assert mine["outputs"] == {"layout": "sidecar", "file": "1.outputs.jsonl.gz"}
        status, headers, body = fetch(srv, "/session/runs/1.outputs.jsonl.gz")
        assert status == 200 and headers["Content-Type"] == "application/gzip" and "Content-Encoding" not in headers
        assert body == (mock_run_file.parent / "small.outputs.jsonl.gz").read_bytes()
        for missing in ("/session/runs/2.json", "/session/runs/0.outputs.jsonl.gz", "/session/runs/01.json",
                        "/session/runs/1.json.bak", "/session/runs/../index.json", "/session/small.json",
                        "/session/runs/1.outputs.jsonl"):
            assert fetch(srv, missing)[0] == 404


def test_session_shows_a_rerun_after_reload_and_reports_a_broken_file(mock_run_file):
    with serving(server.make_server([mock_run_file], port=0)) as srv:
        assert json.loads(fetch(srv, "/session/index.json")[2])["title"] == "Your run logs"
        run = json.loads(mock_run_file.read_text(encoding="utf-8"))
        schema.save(dict(run, id="second-attempt"), mock_run_file)
        assert json.loads(fetch(srv, "/session/runs/0.json")[2])["id"] == "second-attempt"
        mock_run_file.write_text("{}", encoding="utf-8")
        status, _, body = fetch(srv, "/session/runs/0.json")
        assert status == 500 and b"not a valid run log" in body


def test_bundled_run_keeps_its_output_chunks_reachable_in_a_session():
    bundled = os.path.join(ROOT, "data", "runs", "paper", "seed5.json")
    with serving(server.make_server([bundled], port=0)) as srv:
        pointer = json.loads(fetch(srv, "/session/runs/0.json")[2])["outputs"]
        assert pointer == {"layout": "chunks", "base": "../../data/outputs/paper/s5/",
                           "shared": {"greedy-0.0.current": "../../data/outputs/paper/shared/"}}


def test_output_pointer_outside_the_site_is_dropped(mock_loop, tmp_path):
    run = dict(mock_loop[0], outputs={"layout": "chunks", "base": "../../../etc/"})
    path = tmp_path / "pointing.json"
    schema.save(run, path)
    evil = dict(mock_loop[0], outputs={"layout": "sidecar", "file": "../secret.outputs.jsonl.gz"})
    (tmp_path / "sub").mkdir()
    schema.save(evil, tmp_path / "sub" / "evil.json")
    (tmp_path / "secret.outputs.jsonl.gz").write_bytes(b"private")
    with serving(server.make_server([path, tmp_path / "sub" / "evil.json"], port=0)) as srv:
        assert "outputs" not in json.loads(fetch(srv, "/session/runs/0.json")[2])
        assert json.loads(fetch(srv, "/session/index.json")[2])["runs"][1]["outputs"] is None
        assert "outputs" not in json.loads(fetch(srv, "/session/runs/1.json")[2])


def test_bad_run_stops_the_server_before_it_starts(tmp_path):
    with pytest.raises(DriftAuditError, match="no such file"):
        server.make_server([tmp_path / "missing.json"], port=0)


def test_taken_port_moves_to_the_next_one():
    with serving(server.make_server(port=0)) as first:
        taken = first.server_address[1]
        with serving(server.make_server(port=taken)) as second:
            assert taken < second.server_address[1] < taken + server.PORT_TRIES


def test_serve_announces_address_and_warns_off_loopback(monkeypatch):
    said, opened = [], []
    monkeypatch.setattr(server._Server, "serve_forever", lambda self: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    server.serve(None, port=0, open_browser=True, announce=said.append)
    assert len(said) == 1 and said[0].startswith("Workbench at http://127.0.0.1:") and opened[0] in said[0]
    said.clear()
    server.serve(None, host="0.0.0.0", port=0, open_browser=False, announce=said.append)
    assert said[0].startswith("Warning: listening on 0.0.0.0") and "http://127.0.0.1:" in said[1]
    assert len(opened) == 1


def test_sidecar_pointer_must_name_an_outputs_file_next_to_the_run(mock_loop, tmp_path):
    (tmp_path / "tax-return.pdf").write_bytes(b"private")
    (tmp_path / "named.outputs.jsonl").write_bytes(b"{}\n")
    for name, expected in (("tax-return.pdf", None), ("../x.outputs.jsonl", None), (".hidden.outputs.jsonl", None),
                           ("named.outputs.jsonl", "named.outputs.jsonl")):
        run = dict(mock_loop[0], outputs={"layout": "sidecar", "file": name})
        found = server.find_sidecar(tmp_path / "run.json", run)
        assert (found.name if found else None) == expected, name
    assert server.is_sidecar_name("a.outputs.jsonl.gz") and not server.is_sidecar_name("a\\b.outputs.jsonl")
