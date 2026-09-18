"""Тесты логики e-mail оповещений (main.MonitorApp)."""

from __future__ import annotations

from main import MonitorApp
from models import DiffResult, FolderAnomaly, FolderRecord, Move


def _folder(name="folder", root="z:\\root", rel="A", count=0):
    return FolderRecord(
        scan_id=1,
        root=root,
        relative_path=rel,
        folder_name=name,
        level=1,
        file_count=count,
        max_depth=-1,
        content_hash="h",
    )


def test_has_alertable_changes_empty():
    assert MonitorApp._has_alertable_changes(DiffResult()) is False


def test_has_alertable_changes_moved():
    diff = DiffResult(moved=[Move("z:\\root", "A", "B", "docs", "high", 5)])
    assert MonitorApp._has_alertable_changes(diff) is True


def test_has_alertable_changes_deleted():
    diff = DiffResult(deleted=[_folder()])
    assert MonitorApp._has_alertable_changes(diff) is True


def test_has_alertable_changes_anomaly():
    diff = DiffResult(
        file_count_decreased=[FolderAnomaly("z:\\root", "A", "A", 100, 50, 50.0)]
    )
    assert MonitorApp._has_alertable_changes(diff) is True


def test_has_alertable_changes_created_only_is_false():
    diff = DiffResult(created=[_folder()])
    assert MonitorApp._has_alertable_changes(diff) is False


def test_display_path_joins_root_and_relative():
    assert MonitorApp._display_path("z:\\root", "A/B") == "z:\\root\\A\\B"
    assert MonitorApp._display_path("z:\\root", "") == "z:\\root"


def test_build_email_body_contains_details():
    diff = DiffResult(
        moved=[Move("z:\\root", "A", "B", "docs", "high", 5)],
        deleted=[_folder(name="old", rel="C", count=3)],
        file_count_decreased=[FolderAnomaly("z:\\root", "D", "D", 100, 60, 40.0)],
    )

    body = MonitorApp._build_email_body(diff, 42)

    assert "Скан #42" in body
    assert "docs" in body
    assert "high" in body
    assert "old" in body
    assert "40.0%" in body
    assert "Перемещённые папки" in body
    assert "Удалённые папки" in body
    assert "Аномальное уменьшение файлов" in body


def test_build_email_subject_summarizes_changes():
    diff = DiffResult(
        moved=[Move("z:\\root", "A", "B", "docs", "high", 5)],
        deleted=[_folder()],
    )
    subject = MonitorApp._build_email_subject(diff, 7)
    assert "перемещено 1" in subject
    assert "удалено 1" in subject
    assert "#7" in subject


def test_smtp_credentials_from_config(monkeypatch):
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    monkeypatch.delenv("MONITOR_SMTP_PASSWORD", raising=False)
    app = MonitorApp()
    app.alerts = {"smtp_user": "user@x.com", "smtp_password": "secret123"}
    assert app._smtp_credentials() == ("user@x.com", "secret123")


def test_smtp_credentials_env_override(monkeypatch):
    monkeypatch.setenv("MONITOR_SMTP_PASSWORD", "envsecret")
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    app = MonitorApp()
    app.alerts = {"smtp_user": "user@x.com", "smtp_password": "cfgsecret"}
    assert app._smtp_credentials() == ("user@x.com", "envsecret")


def test_smtp_credentials_empty_by_default(monkeypatch):
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    monkeypatch.delenv("MONITOR_SMTP_PASSWORD", raising=False)
    app = MonitorApp()
    app.alerts = {}
    assert app._smtp_credentials() == ("", "")
