"""Тесты скрипта принудительной отправки последнего отчёта."""

from __future__ import annotations

from send_report import find_last_report_attachments


def test_find_last_report_attachments_returns_html_and_related(tmp_path):
    (tmp_path / "report_20260924_120000.html").write_text("old", encoding="utf-8")
    (tmp_path / "report_20260924_120000.csv").write_text("old csv", encoding="utf-8")

    (tmp_path / "report_20260925_090000.html").write_text("new", encoding="utf-8")
    (tmp_path / "report_20260925_090000.csv").write_text("new csv", encoding="utf-8")
    (tmp_path / "moves_20260925_090000.csv").write_text("moves", encoding="utf-8")

    result = find_last_report_attachments(tmp_path)
    names = [p.name for p in result]

    assert names[0] == "report_20260925_090000.html"
    assert "report_20260925_090000.csv" in names
    assert "moves_20260925_090000.csv" in names
    assert "report_20260924_120000.html" not in names


def test_find_last_report_attachments_without_moves(tmp_path):
    (tmp_path / "report_20260925_090000.html").write_text("new", encoding="utf-8")
    (tmp_path / "report_20260925_090000.csv").write_text("new csv", encoding="utf-8")

    names = [p.name for p in find_last_report_attachments(tmp_path)]

    assert names == ["report_20260925_090000.html", "report_20260925_090000.csv"]


def test_find_last_report_attachments_no_reports(tmp_path):
    assert find_last_report_attachments(tmp_path) == []


def test_find_last_report_attachments_missing_dir(tmp_path):
    assert find_last_report_attachments(tmp_path / "Reports") == []
