"""Тесты модуля email_sender (отправка писем с вложениями)."""

from __future__ import annotations

import pytest

import email_sender
from email_sender import EmailSendError, send_email, smtp_credentials


def test_smtp_credentials_from_config(monkeypatch):
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    monkeypatch.delenv("MONITOR_SMTP_PASSWORD", raising=False)
    alerts = {"smtp_user": "user@x.com", "smtp_password": "secret123"}
    assert smtp_credentials(alerts) == ("user@x.com", "secret123")


def test_smtp_credentials_env_override(monkeypatch):
    monkeypatch.setenv("MONITOR_SMTP_PASSWORD", "envsecret")
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    alerts = {"smtp_user": "user@x.com", "smtp_password": "cfgsecret"}
    assert smtp_credentials(alerts) == ("user@x.com", "envsecret")


def test_smtp_credentials_empty_by_default(monkeypatch):
    monkeypatch.delenv("MONITOR_SMTP_USER", raising=False)
    monkeypatch.delenv("MONITOR_SMTP_PASSWORD", raising=False)
    assert smtp_credentials({}) == ("", "")


def test_send_email_with_attachment(monkeypatch, tmp_path):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            calls["host"] = host
            calls["port"] = port
            calls["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            calls["user"] = user
            calls["password"] = password

        def sendmail(self, from_addr, to_addrs, msg):
            calls["from"] = from_addr
            calls["to"] = to_addrs
            calls["msg"] = msg

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)

    attachment = tmp_path / "report_1.html"
    attachment.write_text("<html></html>", encoding="utf-8")

    send_email(
        to="to@example.com",
        subject="Subj",
        body="Body",
        smtp_server="smtp.example.com",
        smtp_port=587,
        from_addr="from@example.com",
        smtp_user="user",
        smtp_password="pass",
        attachments=[attachment],
    )

    assert calls["host"] == "smtp.example.com"
    assert calls["port"] == 587
    assert calls["from"] == "from@example.com"
    assert calls["to"] == ["to@example.com"]
    assert calls["user"] == "user"
    assert calls["password"] == "pass"
    assert "Subject: Subj" in calls["msg"]
    assert "report_1.html" in calls["msg"]


def test_send_email_without_login_when_no_user(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            calls["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, msg):
            calls["sent"] = True

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)

    send_email(
        to="to@example.com",
        subject="Subj",
        body="Body",
        smtp_server="smtp.example.com",
        smtp_port=587,
    )

    assert "login" not in calls
    assert calls.get("sent") is True


def test_send_email_missing_attachment_raises(tmp_path):
    with pytest.raises(EmailSendError):
        send_email(
            to="to@example.com",
            subject="S",
            body="B",
            smtp_server="smtp.example.com",
            smtp_port=587,
            attachments=[tmp_path / "missing.html"],
        )


def test_send_email_smtp_failure_wrapped(monkeypatch):
    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            pass

        def ehlo(self):
            pass

        def starttls(self):
            raise ConnectionError("boom")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)

    with pytest.raises(EmailSendError) as excinfo:
        send_email(
            to="to@example.com",
            subject="S",
            body="B",
            smtp_server="smtp.example.com",
            smtp_port=587,
        )
    message = str(excinfo.value)
    assert "STARTTLS" in message
    assert "smtp.example.com:587" in message
    assert "ConnectionError" in message
    assert "boom" in message


def test_send_email_connect_failure_mentions_server(monkeypatch):
    def broken_smtp(host, port, timeout=30):
        raise OSError("network unreachable")

    monkeypatch.setattr(email_sender.smtplib, "SMTP", broken_smtp)

    with pytest.raises(EmailSendError) as excinfo:
        send_email(
            to="to@example.com",
            subject="S",
            body="B",
            smtp_server="smtp.example.com",
            smtp_port=25,
        )
    message = str(excinfo.value)
    assert "Подключение" in message
    assert "smtp.example.com:25" in message
    assert "OSError" in message
    assert "network unreachable" in message
