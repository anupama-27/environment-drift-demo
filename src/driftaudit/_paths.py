"""Where the workbench files live, and the two file helpers the server, the report builder
and the CLI share."""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional, Sequence, Union

from .errors import DriftAuditError

# The top-level entries that make up the site. The wheel ships exactly these, and the local
# server serves nothing else, so an editable install never exposes the rest of the checkout.
SITE_ENTRIES = ("index.html", "favicon.svg", "assets", "data", "replay")


def web_dir() -> Path:
    """Directory holding index.html, assets/, data/ and replay/.

    A wheel carries the site inside the package as driftaudit/web. An editable install has no
    such copy, so the repository root two levels above src/driftaudit is used instead.
    """
    package = Path(__file__).resolve().parent
    packaged = package / "web"
    if (packaged / "index.html").is_file():
        return packaged
    checkout = package.parent.parent
    if (checkout / "index.html").is_file():
        return checkout
    raise DriftAuditError(
        "The workbench files are missing from this installation (no index.html in "
        f"{packaged} or {checkout}). Reinstall driftaudit, or run it from a checkout of the "
        "repository.")


def resolve_inside(root: Union[str, Path], parts: Sequence[str]) -> Optional[Path]:
    """The file root/parts[0]/parts[1]/..., or None when it is not a regular file inside root.

    Both sides go through realpath, so a symlink that points out of the directory fails the
    same check as `..` does.
    """
    if not parts:
        return None
    for part in parts:
        # A leading dot covers "." and ".." as well as hidden files; a colon covers Windows
        # drive letters and alternate data streams.
        if not part or part.startswith(".") or any(c in part for c in "/\\:\x00"):
            return None
    base = os.path.realpath(os.fspath(root))
    target = os.path.realpath(os.path.join(base, *parts))
    try:
        if os.path.commonpath([base, target]) != base:
            return None
    except ValueError:  # different drives on Windows
        return None
    if target == base or not os.path.isfile(target):
        return None
    return Path(target)


def write_atomic(path: Union[str, Path], data: bytes) -> Path:
    """Write to a temporary file next to the target and rename it into place.

    A reader never sees a half-written file, and an interrupted write leaves the previous
    version untouched. The temporary file is created with mode 0666, which the umask then
    narrows, so the result has the same permissions as any other new file. tempfile.mkstemp
    would leave it readable by the owner only.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(tmp, flags, 0o666)
        with open(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        raise DriftAuditError(f"cannot write {path}: {exc.strerror or exc}") from exc
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return path
