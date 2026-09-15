"""Тесты сканера папок (scanner)."""

from __future__ import annotations

import hashlib
import logging

from models import RootConfig
from scanner import FolderScanner


def _scanner(count_hidden=True):
    return FolderScanner({"count_hidden_files": count_hidden}, logging.getLogger("test"))


def test_scan_with_individual_depth(tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    (root / "f_root.txt").write_text("x")
    (root / "a" / "f_a.txt").write_text("x")
    (root / "a" / "b" / "f_b.txt").write_text("x")
    (root / "c" / "f_c.txt").write_text("x")

    result = _scanner().scan_root(RootConfig(str(root), 1), scan_id=1)
    paths = {f.relative_path for f in result.folders}

    assert "" in paths          # корень (уровень 0)
    assert "a" in paths         # уровень 1
    assert "c" in paths         # уровень 1
    assert "a/b" not in paths   # уровень 2 — не сканируется при глубине 1


def test_scan_zero_depth_only_root(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "f.txt").write_text("x")

    result = _scanner().scan_root(RootConfig(str(root), 0), scan_id=1)
    paths = {f.relative_path for f in result.folders}
    assert paths == {""}


def test_file_count_only_current_folder(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("x")
    (root / "b.txt").write_text("x")
    (root / "sub" / "c.txt").write_text("x")

    result = _scanner().scan_root(RootConfig(str(root), -1), scan_id=1)
    by_path = {f.relative_path: f for f in result.folders}

    # Файлы считаются только в самой папке, без вложенных.
    assert by_path[""].file_count == 2
    assert by_path["sub"].file_count == 1


def test_content_hash_uses_only_names():
    scanner = _scanner()

    h1 = scanner._compute_content_hash(["b.txt", "a.txt"])
    h2 = scanner._compute_content_hash(["a.txt", "b.txt"])
    assert h1 == h2  # порядок имён не важен (список сортируется)

    empty = scanner._compute_content_hash([])
    assert empty == hashlib.sha256(b"").hexdigest()


def test_content_hash_differs_by_names():
    scanner = _scanner()
    assert scanner._compute_content_hash(["a.txt"]) != scanner._compute_content_hash(["b.txt"])


def test_hidden_files_skipped(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("x")
    (root / ".hidden").write_text("x")
    (root / "desktop.ini").write_text("x")

    result = _scanner(count_hidden=False).scan_root(RootConfig(str(root), 0), scan_id=1)
    assert result.folders[0].file_count == 1


def test_hidden_files_counted_by_default(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("x")
    (root / ".hidden").write_text("x")
    (root / "desktop.ini").write_text("x")

    result = _scanner(count_hidden=True).scan_root(RootConfig(str(root), 0), scan_id=1)
    assert result.folders[0].file_count == 3


def test_missing_root_reports_error(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = _scanner().scan_root(RootConfig(str(missing), -1), scan_id=1)
    assert result.folder_count == 0
    assert len(result.errors) == 1
