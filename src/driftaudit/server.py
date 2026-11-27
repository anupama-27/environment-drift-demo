"""Local server behind `driftaudit demo` and `driftaudit view`.

It serves the workbench files and, for `view`, the run logs named on the command line under
session/ (see .10x/specs/contracts-web.md, section 5). Nothing else on the machine is
reachable through it: static paths are checked against the site directory after resolving
symlinks, session files are looked up by position and never by a path from the request, and
by default it listens on the loopback interface only.
"""
from __future__ import annotations

import errno
import http.server
import ipaddress
import json
import logging
import os
import shutil
import socket
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Sequence, Tuple, Union, cast

from . import schema
from ._paths import SITE_ENTRIES, resolve_inside, web_dir
from .errors import DriftAuditError

DEFAULT_PORT = 8765
PORT_TRIES = 20
SESSION_TITLE = "Your run logs"

# Fixed here rather than taken from the mimetypes module, whose answers depend on the machine
# (on some Windows setups .js comes back as text/plain and the scripts do not run).
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    # Sent as a plain download with no Content-Encoding: the page unpacks it itself, and a
    # browser that did it first would hand the page text it then fails to unpack.
    ".gz": "application/gzip",
}

Body = Union[bytes, Path]


# The workbench loads only its own files and has no inline scripts or styles.
CONTENT_SECURITY_POLICY = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                           "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
                           "frame-ancestors 'none'")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_sidecar_name(name: str) -> bool:
    """A plain file name, in the run log's own directory, of the kind `driftaudit run` writes."""
    return (bool(name) and os.path.basename(name) == name and "\\" not in name and not name.startswith(".")
            and name.endswith((".outputs.jsonl", ".outputs.jsonl.gz")))


def find_sidecar(run_path: Path, run: Dict[str, Any]) -> Optional[Path]:
    """The raw outputs file that sits next to a run log, if there is one."""
    names = []
    pointer = run.get("outputs")
    if isinstance(pointer, dict) and pointer.get("layout") == "sidecar" and isinstance(pointer.get("file"), str):
        # The pointer comes from the run log, so it counts only as a bare name of an outputs
        # file: it must not be able to point at another file, here or anywhere else.
        name = pointer["file"]
        if is_sidecar_name(name):
            names.append(name)
    stem = run_path.name[:-5] if run_path.name.endswith(".json") else run_path.name
    names += [f"{stem}.outputs.jsonl.gz", f"{stem}.outputs.jsonl"]
    for name in names:
        candidate = run_path.parent / name
        if candidate.is_file():
            return candidate
    return None


class Session:
    """The run logs given to `driftaudit view`."""

    def __init__(self, run_paths: Sequence[Union[str, Path]], title: Optional[str], web: Path) -> None:
        self.title = title or SESSION_TITLE
        self.web = web
        self.paths = [Path(p) for p in run_paths]
        # Loaded once up front so that a bad file stops the command with a clear message
        # before a browser opens. Requests read the files again, so a rerun shows on reload.
        self.sidecars = [find_sidecar(path, schema.load(path)) for path in self.paths]

    def _outputs_name(self, index: int) -> Optional[str]:
        sidecar = self.sidecars[index]
        if sidecar is None:
            return None
        return f"{index}.outputs.jsonl.gz" if sidecar.name.endswith(".gz") else f"{index}.outputs.jsonl"

    def index(self) -> bytes:
        runs = []
        for i, path in enumerate(self.paths):
            outputs = self._outputs_name(i)
            runs.append({"name": path.name, "url": f"session/runs/{i}.json",
                         "outputs": f"session/runs/{outputs}" if outputs else None})
        return json.dumps({"title": self.title, "runs": runs}).encode("utf-8")

    def run(self, index: int) -> bytes:
        run = schema.load(self.paths[index])
        pointer = self._pointer(index, run)
        if pointer is None:
            run.pop("outputs", None)
        else:
            run["outputs"] = pointer
        return json.dumps(run, separators=(",", ":")).encode("utf-8")

    def _pointer(self, index: int, run: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Where the page finds this run's raw outputs, relative to session/runs/<index>.json."""
        name = self._outputs_name(index)
        if name is not None:
            return {"layout": "sidecar", "file": name}
        pointer = run.get("outputs")
        if not (isinstance(pointer, dict) and pointer.get("layout") == "chunks"):
            return None
        # Chunk folders are only reachable when they are part of the site, as the bundled
        # paper outputs are. Their addresses are rewritten to start from session/runs/.
        shared = pointer.get("shared") or {}
        if not isinstance(shared, dict):
            return None
        base = self._site_address(index, pointer.get("base"))
        moved = {label: self._site_address(index, folder) for label, folder in shared.items()}
        if base is None or None in moved.values():
            return None
        out: Dict[str, Any] = {"layout": "chunks", "base": base}
        if moved:
            out["shared"] = moved
        return out

    def _site_address(self, index: int, folder: Any) -> Optional[str]:
        """A folder given relative to run log `index`, as seen from session/runs/; None if it
        is not inside the site."""
        if not isinstance(folder, str):
            return None
        root = os.path.realpath(self.web)
        target = os.path.realpath(os.path.join(self.paths[index].parent, folder))
        try:
            if os.path.commonpath([root, target]) != root or target == root:
                return None
        except ValueError:
            return None
        parts = Path(os.path.relpath(target, root)).parts
        if parts[0] not in SITE_ENTRIES:
            return None
        return "../../" + "/".join(parts) + "/"

    def lookup(self, parts: List[str]) -> Optional[Tuple[Body, str]]:
        """(body, content type) for a path below session/, or None."""
        if parts == ["index.json"]:
            return self.index(), CONTENT_TYPES[".json"]
        if len(parts) != 2 or parts[0] != "runs":
            return None
        number, _, rest = parts[1].partition(".")
        if not number.isdigit() or int(number) >= len(self.paths) or str(int(number)) != number:
            return None
        index = int(number)
        if rest == "json":
            return self.run(index), CONTENT_TYPES[".json"]
        sidecar = self.sidecars[index]
        if sidecar is not None and parts[1] == self._outputs_name(index) and sidecar.is_file():
            return sidecar, CONTENT_TYPES[".gz" if parts[1].endswith(".gz") else ".jsonl"]
        return None


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "driftaudit"
    sys_version = ""

    def do_GET(self) -> None:
        self._respond(send_body=True)

    def do_HEAD(self) -> None:
        self._respond(send_body=False)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def version_string(self) -> str:
        return self.server_version

    def _respond(self, send_body: bool) -> None:
        body: Body = b"Not found\n"
        status, content_type = 404, CONTENT_TYPES[".txt"]
        if not self._host_allowed():
            status, body = 403, b"Forbidden\n"
        else:
            try:
                found = self._find()
            except DriftAuditError as exc:
                # A run log that was valid when the server started and has since been replaced
                # by something that is not one.
                status, body = 500, f"{exc}\n".encode("utf-8")
            else:
                if found is not None:
                    status, (body, content_type) = 200, found
        self._send(status, body, content_type, send_body)

    def _host_allowed(self) -> bool:
        """Refuse requests that reach a loopback server under some other host name.

        That is how a web page on another site gets at a local server (DNS rebinding): the
        browser is told the site's name now points at 127.0.0.1, and sends that name here.
        """
        if not cast(_Server, self.server).loopback_only:
            return True
        host = self.headers.get("Host")
        if host is None:
            return True
        try:
            name = urllib.parse.urlsplit("//" + host).hostname or ""
        except ValueError:
            return False
        return _is_loopback(name)

    def _find(self) -> Optional[Tuple[Body, str]]:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/"):
            return None
        parts = urllib.parse.unquote(path).split("/")[1:]
        if parts == [""]:
            parts = ["index.html"]
        server = cast(_Server, self.server)
        if parts[0] == "session":
            return server.session.lookup(parts[1:]) if server.session is not None else None
        if parts[0] not in SITE_ENTRIES:
            return None
        target = resolve_inside(server.web, parts)
        if target is None:
            return None
        return target, CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")

    def _send(self, status: int, body: Body, content_type: str, send_body: bool) -> None:
        stream: Optional[BinaryIO] = None
        if isinstance(body, Path):
            try:
                stream = open(body, "rb")
            except OSError:
                status, body, content_type = 404, b"Not found\n", CONTENT_TYPES[".txt"]
        try:
            length = os.fstat(stream.fileno()).st_size if stream is not None else len(cast(bytes, body))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            # Run logs change between two looks at the same address; nothing may be reused.
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.end_headers()
            if send_body:
                if stream is not None:
                    shutil.copyfileobj(stream, self.wfile)
                else:
                    self.wfile.write(cast(bytes, body))
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser went away mid-response
        finally:
            if stream is not None:
                stream.close()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # On Windows the option lets a second process bind a port that is already being served,
    # which would defeat the search for a free one.
    allow_reuse_address = os.name != "nt"
    web: Path
    session: Optional[Session]
    loopback_only: bool


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(run_paths: Optional[Sequence[Union[str, Path]]] = None, *, host: str = "127.0.0.1",
                port: int = DEFAULT_PORT, title: Optional[str] = None,
                web: Union[str, Path, None] = None) -> _Server:
    """A bound server that is not serving yet. Port 0 asks the system for any free port.

    If the port is taken the next ones are tried. `web` replaces the packaged site directory.
    """
    root = Path(web) if web is not None else web_dir()
    session = Session(run_paths, title, root) if run_paths else None
    server_class = _Server6 if ":" in host else _Server
    last = min(port + PORT_TRIES, 65536) if port else 1
    for candidate in range(port, last):
        try:
            server = server_class((host, candidate), _Handler)
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                continue
            raise DriftAuditError(f"Cannot listen on {host} port {candidate}: {exc.strerror or exc}.") from None
        server.web = root
        server.session = session
        server.loopback_only = _is_loopback(host)
        return server
    raise DriftAuditError(f"Ports {port} to {last - 1} are all in use. Choose another with --port.")


def server_url(server: _Server) -> str:
    """Address to open in a browser on this machine."""
    host, port = server.server_address[0], server.server_address[1]
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}/" + ("?session=1" if server.session is not None else "")


def serve(run_paths: Optional[Sequence[Union[str, Path]]] = None, *, host: str = "127.0.0.1",
          port: int = DEFAULT_PORT, open_browser: bool = True, title: Optional[str] = None,
          announce: Optional[Callable[[str], None]] = None) -> None:
    """Serve the workbench until interrupted.

    Without run paths it shows the bundled runs. With them it also serves those run logs and
    opens the page on them. Status lines go to `announce` (the CLI prints them), or to the
    `driftaudit.server` logger when it is left out.
    """
    say = announce or logging.getLogger(__name__).info
    server = make_server(run_paths, host=host, port=port, title=title)
    try:
        if port and server.server_address[1] != port:
            say(f"Port {port} is in use, so this is on port {server.server_address[1]}.")
        if not server.loopback_only:
            say(f"Warning: listening on {host}, so other machines on the network can read the "
                "workbench and the run logs opened in it.")
        url = server_url(server)
        say(f"Workbench at {url} (Ctrl-C to stop)")
        if open_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                pass
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
