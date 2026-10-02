"""Тесты функции логирования запуска скрипта."""

from __future__ import annotations

import logging

from logger_setup import log_startup


def test_log_startup_records_banner(caplog):
    with caplog.at_level(logging.INFO):
        log_startup(logging.getLogger("test_startup"), "тестового скрипта", __file__)

    messages = [r.getMessage() for r in caplog.records]
    text = " | ".join(messages)

    assert "Запуск тестового скрипта" in text
    assert "Скрипт:" in text
    assert "Аргументы:" in text
    assert "Рабочая папка:" in text
    assert "PID:" in text


def test_log_startup_logs_entry_bat(monkeypatch, caplog):
    monkeypatch.setenv("MONITOR_ENTRY_BAT", "run_monitor.bat")

    with caplog.at_level(logging.INFO):
        log_startup(logging.getLogger("test_startup_bat"), "мониторинга", __file__)

    messages = [r.getMessage() for r in caplog.records]
    text = " | ".join(messages)
    assert "Запуск через: run_monitor.bat" in text


def test_log_startup_without_entry_bat(monkeypatch, caplog):
    monkeypatch.delenv("MONITOR_ENTRY_BAT", raising=False)

    with caplog.at_level(logging.INFO):
        log_startup(logging.getLogger("test_startup_nobat"), "мониторинга", __file__)

    messages = [r.getMessage() for r in caplog.records]
    text = " | ".join(messages)
    assert "Запуск через:" not in text
