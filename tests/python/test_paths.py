"""Locating the site, containment of paths, and atomic writes."""
from __future__ import annotations

import os

import pytest

from conftest import ROOT
from driftaudit import _paths
from driftaudit.errors import DriftAuditError


def test_editable_install_uses_the_checkout():
    web = _paths.web_dir()
    assert str(web) == os.path.realpath(ROOT)
    assert all((web / entry).exists() for entry in _paths.SITE_ENTRIES)


def test_packaged_site_wins_then_checkout_then_a_clear_error(tmp_path, monkeypatch):
    package = tmp_path / "src" / "driftaudit"
    package.mkdir(parents=True)
    monkeypatch.setattr(_paths, "__file__", str(package / "_paths.py"))
    with pytest.raises(DriftAuditError, match="workbench files are missing"):
        _paths.web_dir()
    (tmp_path / "index.html").write_text("checkout", encoding="utf-8")
    assert _paths.web_dir() == tmp_path.resolve()
    (package / "web").mkdir()
    (package / "web" / "index.html").write_text("wheel", encoding="utf-8")
    assert _paths.web_dir() == (package / "web").resolve()


def test_resolve_inside_only_returns_files_below_the_root(tmp_path):
    (tmp_path / "site" / "assets").mkdir(parents=True)
    (tmp_path / "site" / "assets" / "a.css").write_text("x", encoding="utf-8")
    (tmp_path / "site" / "assets" / ".hidden").write_text("x", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("x", encoding="utf-8")
    root = tmp_path / "site"
    assert _paths.resolve_inside(root, ["assets", "a.css"]) == (root / "assets" / "a.css").resolve()
    for parts in ([], ["assets"], ["assets", "missing.css"], ["..", "outside.txt"], ["assets", "..", "..", "outside.txt"],
                  ["assets", ".hidden"], ["assets", ""], ["assets/a.css"], ["assets\\a.css"], ["C:", "a.css"],
                  ["assets", "a.css\x00"], [str(tmp_path / "outside.txt")]):
        assert _paths.resolve_inside(root, parts) is None


def test_write_atomic_replaces_the_file_and_leaves_nothing_behind(tmp_path):
    target = tmp_path / "out.txt"
    assert _paths.write_atomic(target, b"one") == target
    _paths.write_atomic(str(target), b"two")
    assert target.read_bytes() == b"two" and os.listdir(tmp_path) == ["out.txt"]
    with pytest.raises(DriftAuditError, match="cannot write"):
        _paths.write_atomic(tmp_path / "no" / "dir" / "x.txt", b"x")
    assert os.listdir(tmp_path) == ["out.txt"]
