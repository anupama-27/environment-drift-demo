"""The single-file report: everything inlined, nothing fetched."""
from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest

from app_fixtures import PAPER_SEED5, mock_loop, mock_run_file  # noqa: F401
from driftaudit import report, schema
from driftaudit.errors import DriftAuditError

INDEX = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Workbench</title>
<meta property="og:image" content="https://example.org/preview.png">
<!-- <script src="assets/js/old.js"></script> -->
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="preload" href="assets/fonts/f.woff2" as="font" crossorigin>
<link rel="stylesheet" href="assets/css/a.css?v=3">
<link href='assets/css/b.css' rel='stylesheet' media="print">
</head><body>
<main id="app"></main>
<script src="assets/js/a.js"></script>
<script src="assets/js/late.js?v=2" defer></script>
<script src="assets/js/b.js?v=9"></script>
</body></html>
"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    for folder in ("assets/css", "assets/js", "assets/fonts"):
        (root / folder).mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    (root / "assets/fonts/f.woff2").write_bytes(b"\x00font\xff")
    (root / "assets/css/a.css").write_text(
        '@font-face { font-family: F; src: url("../fonts/f.woff2") format("woff2"); }\n'
        "/* </style> in a comment */ a { background: url(data:image/png;base64,AAAA); fill: url(#grad); }\n",
        encoding="utf-8")
    (root / "assets/css/b.css").write_text("b { src: url(../fonts/f.woff2?v=1) }", encoding="utf-8")
    (root / "assets/js/a.js").write_text('var A = "</script><!-- not markup -->";\n', encoding="utf-8")
    (root / "assets/js/b.js").write_text("var B = A.length;\n", encoding="utf-8")
    (root / "assets/js/late.js").write_text("var LATE = true;\n", encoding="utf-8")
    return root


def embedded(page):
    match = re.search(r'<script type="application/json" id="da-embedded">(.*?)</script>', page, flags=re.S)
    return json.loads(match.group(1)), match


def test_fixture_site_becomes_one_self_contained_document(site, mock_loop):
    run = dict(mock_loop[0])
    run["prompts"] = dict(run["prompts"], evil="</script><script>alert(1)</script><!--")
    page = report.render_report(site, [run], "A & B <report>")
    assert report.external_references(page) == []
    assert "<title>A &amp; B &lt;report&gt;</title>" in page and "og:image" not in page and "preload" not in page
    assert "old.js" not in page

    font = base64.b64encode(b"\x00font\xff").decode()
    assert page.count(f'url("data:font/woff2;base64,{font}")') == 2
    assert "url(data:image/png;base64,AAAA)" in page and "url(#grad)" in page
    assert '<style media="print">' in page and "<\\/style> in a comment" in page
    assert 'href="data:image/svg+xml;base64,' in page

    data, match = embedded(page)
    assert data == {"title": "A & B <report>", "runs": [run]}
    assert "<" not in match.group(1)
    blocks = re.findall(r"<script>\n(.*?)\n</script>", page, flags=re.S)
    assert blocks == ['var A = "<\\/script><\\!-- not markup -->";\n', "var B = A.length;\n", "var LATE = true;\n"]
    assert match.start() < page.index("<script>\n")
    assert page.count("</script>") == 4 and page.rstrip().endswith("</body></html>")


def test_site_that_cannot_be_inlined_is_refused(site):
    index = site / "index.html"
    for change, hint in (
            (("assets/js/b.js?v=9", "assets/js/missing.js"), "not a file inside"),
            (("assets/js/b.js?v=9", "https://cdn.example/x.js"), "from the network"),
            (("assets/css/a.css?v=3", "//cdn.example/x.css"), "from the network"),
            (("assets/js/a.js", "../outside.js"), "not a file inside"),
            (('<script src="assets/js/a.js">', '<script type="module" src="assets/js/a.js">'), "as a module"),
            (('<main id="app"></main>', '<main id="app"></main><iframe src="other.html"></iframe>'), "still load files")):
        index.write_text(INDEX.replace(*change), encoding="utf-8")
        with pytest.raises(DriftAuditError, match=hint):
            report.render_report(site, [], "t")
    index.write_text(INDEX, encoding="utf-8")
    (site / "assets/css/b.css").write_text('@import "c.css";', encoding="utf-8")
    with pytest.raises(DriftAuditError, match="@import"):
        report.render_report(site, [], "t")
    (site / "assets/css/b.css").write_text("b { background: url(https://example.org/x.png) }", encoding="utf-8")
    with pytest.raises(DriftAuditError, match="from the network"):
        report.render_report(site, [], "t")


def test_images_are_inlined_and_pages_without_scripts_still_get_the_data(site):
    (site / "index.html").write_text(
        "<html><head></head><body><img alt='x' src='favicon.svg'><a href='https://example.org'>out</a></body></html>",
        encoding="utf-8")
    page = report.render_report(site, [], "Plain")
    assert "<img alt='x' src=\"data:image/svg+xml;base64," in page and report.external_references(page) == []
    assert embedded(page)[0] == {"title": "Plain", "runs": []} and "<title>Plain</title></head>" in page


def test_report_on_the_real_site_embeds_slim_runs(tmp_path, mock_run_file):
    out = report.build_report([PAPER_SEED5, mock_run_file], tmp_path / "report.html")
    page = out.read_text(encoding="utf-8")
    assert out == tmp_path / "report.html" and sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".html") == ["report.html"]
    assert report.external_references(page) == []
    data, _ = embedded(page)
    assert data["title"] == "DriftAudit report: 2 runs" and "<title>DriftAudit report: 2 runs</title>" in page
    paper, mine = data["runs"]
    assert paper["id"] == "gsm8k-qwen2.5-1.5b-seed5" and mine["source"] == "synthetic"
    for run in data["runs"]:
        assert schema.validate(run) == [] and "outputs" not in run and "passes" not in run["meta"]["config"]
    assert paper["labels"] == schema.load(PAPER_SEED5)["labels"]
    assert not re.search(r"<script\b[^>]*\bsrc=", page) and not re.search(r"<link\b[^>]*stylesheet", page)
    single = report.build_report([mock_run_file], tmp_path / "one.html").read_text(encoding="utf-8")
    assert embedded(single)[0]["title"] == "DriftAudit report: gsm8k-driftaudit-mock-seed1"


def test_report_carries_the_favicon_inside_itself(tmp_path):
    from driftaudit._paths import web_dir
    assert '<link rel="icon" href="favicon.svg" type="image/svg+xml">' in (web_dir() / "index.html").read_text(encoding="utf-8")
    page = report.build_report([PAPER_SEED5], tmp_path / "r.html").read_text(encoding="utf-8")
    icons = re.findall(r'<link rel="icon" href="data:image/svg\+xml;base64,([^"]+)">', page)
    assert [base64.b64decode(icon) for icon in icons] == [(web_dir() / "favicon.svg").read_bytes()]
    assert "favicon.svg" not in page


def test_report_on_a_bundled_paper_run_loads_no_site_files(tmp_path):
    from driftaudit._paths import web_dir
    page = report.build_report([web_dir() / "data" / "runs" / "paper" / "seed5.json"],
                               tmp_path / "r.html").read_text(encoding="utf-8")
    for reference in ('src="assets/', 'href="assets/', "url(../fonts"):
        assert reference not in page
    data, _ = embedded(page)
    assert [run["id"] for run in data["runs"]] == ["gsm8k-qwen2.5-1.5b-seed5"]


def test_report_needs_runs_and_valid_json_numbers(tmp_path, mock_loop):
    with pytest.raises(DriftAuditError, match="at least one run log"):
        report.build_report([], tmp_path / "r.html")
    with pytest.raises(DriftAuditError, match="no such file"):
        report.build_report([tmp_path / "missing.json"], tmp_path / "r.html")
    with pytest.raises(DriftAuditError, match="NaN or Infinity"):
        report.embedded_json({"runs": [dict(mock_loop[0], meta={"x": float("nan")})]})
    assert not (tmp_path / "r.html").exists()


def test_without_passes_leaves_the_original_alone(mock_loop):
    run = mock_loop[0]
    slim = report.without_passes(run)
    assert "passes" in run["meta"]["config"] and "passes" not in slim["meta"]["config"]
    assert slim["meta"]["config"]["rounds"] == 6 and slim["labels"] is run["labels"]
    assert report.without_passes({"meta": {}}) == {"meta": {}}


def test_report_carries_a_content_policy_built_from_its_own_blocks(site, mock_loop):
    index = (site / "index.html").read_text(encoding="utf-8")
    (site / "index.html").write_text(index.replace(
        '<meta charset="utf-8">',
        '<meta charset="utf-8">\n<meta http-equiv="Content-Security-Policy" content="default-src \'self\'">'), encoding="utf-8")
    page = report.render_report(site, [mock_loop[0]], "Report")
    metas = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', page)
    assert len(metas) == 1, "the site's own policy is replaced, not kept beside the new one"
    policy = dict(part.split(" ", 1) for part in metas[0].replace("&#x27;", "'").split("; "))
    assert policy["default-src"] == "'none'" and policy["connect-src"] == "'none'"
    assert policy["img-src"] == "data:" and policy["font-src"] == "data:"
    assert policy["base-uri"] == "'none'" and policy["form-action"] == "'none'"
    assert page.index("Content-Security-Policy") < page.index("<style")

    def hashes(bodies):
        return {"'sha256-" + base64.b64encode(hashlib.sha256(b.encode("utf-8")).digest()).decode("ascii") + "'" for b in bodies}

    scripts = [body for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script\s*>", page, flags=re.S | re.I)
               if "application/json" not in attrs]
    styles = re.findall(r"<style\b[^>]*>(.*?)</style\s*>", page, flags=re.S | re.I)
    assert len(scripts) == 3 and len(styles) == 2
    assert set(policy["script-src"].split()) == hashes(scripts)
    assert set(policy["style-src"].split()) == hashes(styles)
    assert "unsafe-inline" not in metas[0]
