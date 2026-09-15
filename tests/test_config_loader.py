"""Тесты разбора конфигурации (config_loader)."""

from __future__ import annotations

from config_loader import ConfigLoader, build_paths
from models import RootConfig


def test_parse_root_line_with_depth():
    loader = ConfigLoader(__import__("pathlib").Path("."))
    root = loader._parse_root_line(r"\\server\share;3")
    assert isinstance(root, RootConfig)
    assert root.path == r"\\server\share"
    assert root.max_depth == 3


def test_parse_root_line_without_depth():
    loader = ConfigLoader(__import__("pathlib").Path("."))
    root = loader._parse_root_line(r"\\server\share")
    assert root.max_depth == -1


def test_parse_root_line_invalid_depth():
    loader = ConfigLoader(__import__("pathlib").Path("."))
    root = loader._parse_root_line(r"\\server\share;not-a-number")
    assert root.path == r"\\server\share"
    assert root.max_depth == -1


def test_parse_root_line_zero_depth():
    loader = ConfigLoader(__import__("pathlib").Path("."))
    root = loader._parse_root_line(r"D:\Docs;0")
    assert root.path == r"D:\Docs"
    assert root.max_depth == 0


def test_parse_root_line_ignores_spaces_around_separator():
    loader = ConfigLoader(__import__("pathlib").Path("."))
    root = loader._parse_root_line(r"\\server\share ; 3")
    assert root.path == r"\\server\share"
    assert root.max_depth == 3


def test_load_full_config(tmp_path):
    """Полная загрузка config.ini с форматом 'путь;глубина'."""
    (tmp_path / "config.ini").write_text(
        "\n".join(
            [
                "[ROOTS]",
                r"root1 = \\server\docs;2",
                r"root2 = \\server\archive",
                "",
                "[OPTIONS]",
                "retention_days = 5",
                "count_hidden_files = false",
            ]
        ),
        encoding="utf-8",
    )

    loader = ConfigLoader(tmp_path)
    roots, options = loader.load(config_path=tmp_path / "config.ini")

    assert len(roots) == 2
    assert roots[0].path == r"\\server\docs"
    assert roots[0].max_depth == 2
    assert roots[1].path == r"\\server\archive"
    assert roots[1].max_depth == -1

    assert options["retention_days"] == "5"
    assert options["count_hidden_files"] == "false"


def test_build_paths_resolves_relative_to_base(tmp_path):
    from models import MonitorPaths

    paths = build_paths(
        tmp_path,
        {"db_path": "data.db", "log_dir": "Log", "report_dir": "Reports"},
    )
    assert isinstance(paths, MonitorPaths)
    assert paths.db_path == tmp_path / "data.db"
    assert paths.log_dir == tmp_path / "Log"
    assert paths.report_dir == tmp_path / "Reports"
