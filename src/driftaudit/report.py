"""Single-file HTML report: the workbench with its styles, scripts, fonts and the given run
logs inlined, so the file opens from disk or from an email with nothing next to it.

The builder relies only on how index.html loads the site (.10x/specs/contracts-web.md,
section 1): plain <link rel="stylesheet" href> and <script src> tags pointing at local files,
and fonts referenced from the CSS with url(...). The run logs travel in a JSON script block
that the page reads instead of fetching anything.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import posixpath
import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Mapping, Match, Optional, Sequence, Union

from . import schema
from ._paths import resolve_inside, web_dir, write_atomic
from .errors import DriftAuditError

EMBED_ID = "da-embedded"

_MIME = {
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
}
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_STYLE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.I | re.S)
_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SHARE_META = re.compile(r"""<meta\b[^>]*\b(?:property|name)\s*=\s*["']?(?:og|twitter):[^>]*>\s*""", re.I)
_TITLE = re.compile(r"<title\b[^>]*>.*?</title\s*>", re.I | re.S)
_CSP_META = re.compile(r"""<meta\b[^>]*\bhttp-equiv\s*=\s*["']?content-security-policy[^>]*>\s*""", re.I)
_HEAD = re.compile(r"<head\b[^>]*>", re.I)
_ATTRIBUTE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+)))?""")
_CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)"'\s]*))\s*\)""", re.I)
_LOADING_TAG = re.compile(r"<(?:link|script|img|source|iframe|embed|object|video|audio)\b[^>]*>", re.I)


def _attributes(tag: str) -> Dict[str, str]:
    """Attributes of an opening tag, names in lower case."""
    inner = tag.strip()[1:].rstrip(">").rstrip("/").split(None, 1)
    out: Dict[str, str] = {}
    for match in _ATTRIBUTE.finditer(inner[1] if len(inner) > 1 else ""):
        value = next((g for g in match.groups()[1:] if g is not None), "")
        out.setdefault(match.group(1).lower(), html.unescape(value))
    return out


def _is_local(reference: str) -> bool:
    return not re.match(r"(?:[a-z][a-z0-9+.-]*:|//|#)", reference.strip(), flags=re.I)


def _read(web: Path, reference: str, relative_to: str = "") -> bytes:
    """Bytes of a site file named by a URL as it appears in index.html or in a stylesheet."""
    clean = reference.strip().split("#", 1)[0].split("?", 1)[0]   # ?v=6 only busts caches
    clean = urllib.parse.unquote(clean)
    if clean.startswith("/"):
        relative_to, clean = "", clean.lstrip("/")
    target = resolve_inside(web, posixpath.normpath(posixpath.join(relative_to, clean)).split("/"))
    if target is None:
        raise DriftAuditError(
            f"The site refers to {reference!r}, which is not a file inside {web}. The report "
            "cannot be built from an incomplete site.")
    return target.read_bytes()


def _data_uri(web: Path, reference: str, relative_to: str = "") -> str:
    suffix = Path(reference.split("#", 1)[0].split("?", 1)[0]).suffix.lower()
    encoded = base64.b64encode(_read(web, reference, relative_to)).decode("ascii")
    return f"data:{_MIME.get(suffix, 'application/octet-stream')};base64,{encoded}"


def _inline_css(web: Path, href: str) -> str:
    css = _read(web, href).decode("utf-8")
    if re.search(r"@import\b", css):
        raise DriftAuditError(f"{href} uses @import, which the report builder does not follow. "
                              "Load each stylesheet from index.html instead.")
    folder = posixpath.dirname(href.strip().split("?", 1)[0].lstrip("/"))

    def embed(match: Match[str]) -> str:
        reference = next((g for g in match.groups() if g is not None), "")
        if not reference or reference.startswith(("data:", "#")):
            return match.group(0)
        if not _is_local(reference):
            raise DriftAuditError(f"{href} loads {reference!r} from the network; a single-file "
                                  "report can only include local files.")
        fragment = "#" + reference.split("#", 1)[1] if "#" in reference else ""
        return f'url("{_data_uri(web, reference, folder)}{fragment}")'

    # Inside <style> the only sequence that can end the block early is "</style".
    return re.sub(r"</(style)", r"<\\/\1", _CSS_URL.sub(embed, css), flags=re.I)


def _inline_js(web: Path, src: str) -> str:
    js = _read(web, src).decode("utf-8")
    # "</script" would close the block and "<!--" would change how the rest of it is parsed.
    # Both only occur inside string or regex literals, where the added backslash changes nothing.
    return re.sub(r"</(script)", r"<\\/\1", js, flags=re.I).replace("<!--", "<\\!--")


def embedded_json(payload: Mapping[str, Any]) -> str:
    """JSON that is safe inside a <script> block: no "<" survives, so neither "</script>" nor
    "<!--" can appear, whatever the run logs contain."""
    try:
        text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    except ValueError:
        raise DriftAuditError("A run log holds NaN or Infinity, which JSON does not allow and a "
                              "browser cannot read. Remove those values from the run log.") from None
    return text.replace("<", "\\u003c")


def without_passes(run: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of the run without meta.config.passes, the per-pass batch layout.

    It is most of a run log's size and nothing in an audit reads it.
    """
    out = dict(run)
    meta = out.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("config"), dict) and "passes" in meta["config"]:
        config = {name: value for name, value in meta["config"].items() if name != "passes"}
        out["meta"] = dict(meta, config=config)
    return out


def render_report(web: Union[str, Path], runs: Sequence[Mapping[str, Any]], title: str) -> str:
    """The site in `web` as one HTML document with `runs` embedded."""
    web = Path(web)
    try:
        page = (web / "index.html").read_text(encoding="utf-8")
    except OSError as exc:
        raise DriftAuditError(f"Cannot read {web / 'index.html'}: {exc.strerror or exc}") from exc
    page = _COMMENT.sub("", page)
    page = _SHARE_META.sub("", page)

    def link(match: Match[str]) -> str:
        attrs = _attributes(match.group(0))
        rel = attrs.get("rel", "").lower().split()
        href = attrs.get("href", "")
        if "stylesheet" in rel:
            if not _is_local(href):
                raise DriftAuditError(f"index.html loads the stylesheet {href!r} from the network; "
                                      "a single-file report can only include local files.")
            media = f' media="{html.escape(attrs["media"])}"' if attrs.get("media") else ""
            return f"<style{media}>\n{_inline_css(web, href)}\n</style>"
        if "icon" in rel and href and _is_local(href):
            return f'<link rel="icon" href="{_data_uri(web, href)}">'
        # Preloads, canonical links and the like mean nothing for a file opened from disk.
        return ""

    deferred: List[str] = []

    def script(match: Match[str]) -> str:
        attrs = _attributes("<script " + match.group(1) + ">")
        src = attrs.get("src")
        if src is None:
            return match.group(0)
        if not _is_local(src):
            raise DriftAuditError(f"index.html loads the script {src!r} from the network; "
                                  "a single-file report can only include local files.")
        if attrs.get("type", "").lower() == "module":
            raise DriftAuditError(f"index.html loads {src!r} as a module; the report builder "
                                  "inlines classic scripts only.")
        block = f"<script>\n{_inline_js(web, src)}\n</script>"
        if "defer" in attrs:
            # A deferred script runs once the document is parsed; inline scripts cannot be
            # deferred, so these move to the end of the body, in order.
            deferred.append(block)
            return ""
        return block

    def image(match: Match[str]) -> str:
        src = _attributes(match.group(0)).get("src", "")
        if not src or not _is_local(src):
            return match.group(0)
        return re.sub(r"""\bsrc\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""",
                      lambda _: f'src="{_data_uri(web, src)}"', match.group(0), count=1, flags=re.I)

    page = _LINK.sub(link, page)
    page = _IMG.sub(image, page)
    page = _SCRIPT.sub(script, page)
    if deferred:
        page = _insert_before(page, "</body>", "\n".join(deferred) + "\n")

    data = (f'<script type="application/json" id="{EMBED_ID}">'
            f'{embedded_json({"title": title, "runs": list(runs)})}</script>\n')
    first_script = re.search(r"<script\b", page, flags=re.I)
    if first_script:
        page = page[:first_script.start()] + data + page[first_script.start():]
    else:
        page = _insert_before(page, "</body>", data)

    heading = f"<title>{html.escape(title)}</title>"
    page = _TITLE.sub(lambda _: heading, page, count=1) if _TITLE.search(page) else _insert_before(page, "</head>", heading)

    page = _CSP_META.sub("", page)
    policy = f'<meta http-equiv="Content-Security-Policy" content="{html.escape(content_policy(page))}">\n'
    head = _HEAD.search(page)
    page = page[:head.end()] + "\n" + policy + page[head.end():] if head else policy + page

    leftovers = external_references(page)
    if leftovers:
        raise DriftAuditError("The report would still load files from outside itself: "
                              + ", ".join(leftovers[:5]) + ". index.html does not follow the site "
                              "conventions the report builder relies on.")
    return page


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def content_policy(page: str) -> str:
    """The Content-Security-Policy that fits a report: nothing may load, and only the script
    and style blocks the report carries may run, each allowed by the hash of its text."""
    scripts = [body for attrs, body in _SCRIPT.findall(page)
               if _attributes("<script " + attrs + ">").get("type", "").lower() in ("", "text/javascript")]
    styles = _STYLE.findall(page)
    return "; ".join([
        "default-src 'none'",
        "script-src " + (" ".join(dict.fromkeys(_sha256(body) for body in scripts)) or "'none'"),
        "style-src " + (" ".join(dict.fromkeys(_sha256(body) for body in styles)) or "'none'"),
        "img-src data:",
        "font-src data:",
        "connect-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])


def _insert_before(page: str, closing_tag: str, text: str) -> str:
    position = page.lower().rfind(closing_tag)
    if position < 0:
        return page + text
    return page[:position] + text + page[position:]


def external_references(page: str) -> List[str]:
    """Addresses an HTML document would fetch when opened: tag attributes that load something,
    and url(...) in its style blocks. Empty for a self-contained report."""
    found: List[str] = []
    # Script bodies go first: they are code, and markup inside their strings loads nothing.
    markup = _SCRIPT.sub(lambda m: f"<script {m.group(1)}></script>", page)
    for block in _STYLE.findall(markup):
        for match in _CSS_URL.finditer(block):
            reference = next((g for g in match.groups() if g is not None), "")
            if reference and not reference.startswith(("data:", "#")):
                found.append(reference)
    for tag in _LOADING_TAG.findall(_STYLE.sub("", markup)):
        attrs = _attributes(tag)
        for name in ("src", "href", "data", "poster"):
            value = attrs.get(name, "")
            if value and not value.startswith(("data:", "#")):
                found.append(value)
    return found


def build_report(run_paths: Sequence[Union[str, "os.PathLike[str]"]], out_path: Union[str, "os.PathLike[str]"],
                 *, title: Optional[str] = None) -> Path:
    """Write a self-contained HTML report on the given run logs and return its path.

    Raw outputs are not included, and the run logs are embedded without their batch layout
    (meta.config.passes); the labels, which are what an audit reads, are complete.
    """
    if not run_paths:
        raise DriftAuditError("A report needs at least one run log.")
    runs = []
    for path in run_paths:
        run = without_passes(schema.load(path))
        # The pointer names files that will not be next to the report.
        run.pop("outputs", None)
        runs.append(run)
    if title is None:
        subject = runs[0]["id"] if len(runs) == 1 else f"{len(runs)} runs"
        title = f"DriftAudit report: {subject}"
    return write_atomic(out_path, render_report(web_dir(), runs, title).encode("utf-8"))
