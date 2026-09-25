"""Отправка e-mail через SMTP (STARTTLS) с поддержкой вложений.

Используется как для оповещений в основном цикле мониторинга, так и для
принудительной отправки последнего отчёта через ``send_report.py``.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional, Tuple


class EmailSendError(Exception):
    """Ошибка отправки письма по SMTP."""


def smtp_credentials(alerts: dict) -> Tuple[str, str]:
    """Возвращает (пользователь, пароль) для SMTP-авторизации.

    Приоритет: переменные окружения ``MONITOR_SMTP_USER`` и
    ``MONITOR_SMTP_PASSWORD``, затем опции ``smtp_user`` / ``smtp_password``
    из секции ``[ALERTS]`` конфига.
    """
    user = os.environ.get("MONITOR_SMTP_USER", alerts.get("smtp_user", "")).strip()
    password = os.environ.get(
        "MONITOR_SMTP_PASSWORD", alerts.get("smtp_password", "")
    ).strip()
    return user, password


def send_email(
    to: str,
    subject: str,
    body: str,
    smtp_server: str,
    smtp_port: int,
    from_addr: Optional[str] = None,
    smtp_user: str = "",
    smtp_password: str = "",
    attachments: Optional[List[Path]] = None,
    timeout: int = 30,
) -> None:
    """Отправляет письмо через SMTP с STARTTLS.

    ``attachments`` — список путей к файлам, которые будут вложены в письмо.
    При сбое на любом шаге выбрасывается :class:`EmailSendError`, в сообщении
    которого указаны конкретный этап SMTP-протокола, тип исключения и детали.
    """
    from_addr = from_addr or to

    if attachments:
        message = MIMEMultipart()
        message.attach(MIMEText(body, "plain", "utf-8"))
        for path in attachments:
            path = Path(path)
            if not path.is_file():
                raise EmailSendError(f"Файл вложения не найден: {path}")
            with open(path, "rb") as fh:
                data = fh.read()
            part = MIMEApplication(data)
            part.add_header(
                "Content-Disposition", "attachment", filename=path.name
            )
            message.attach(part)
    else:
        message = MIMEText(body, "plain", "utf-8")

    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to

    # Подключение — отдельный этап: здесь чаще всего проявляются неверные
    # адрес/порт сервера или проблемы сети.
    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=timeout)
    except Exception as exc:
        raise EmailSendError(
            f"Подключение к SMTP-серверу {smtp_server}:{smtp_port} не удалось "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    try:
        try:
            server.ehlo()
        except Exception as exc:
            raise EmailSendError(
                f"EHLO на {smtp_server}:{smtp_port} не удался "
                f"({type(exc).__name__}): {exc}"
            ) from exc

        try:
            server.starttls()
        except Exception as exc:
            raise EmailSendError(
                f"STARTTLS на {smtp_server}:{smtp_port} не удался "
                f"({type(exc).__name__}): {exc}"
            ) from exc

        try:
            server.ehlo()
        except Exception as exc:
            raise EmailSendError(
                f"EHLO после STARTTLS не удался ({type(exc).__name__}): {exc}"
            ) from exc

        if smtp_user:
            try:
                server.login(smtp_user, smtp_password)
            except Exception as exc:
                raise EmailSendError(
                    f"Авторизация {smtp_user} на {smtp_server}:{smtp_port} "
                    f"не удалась ({type(exc).__name__}): {exc}"
                ) from exc

        try:
            server.sendmail(from_addr, [to], message.as_string())
        except Exception as exc:
            raise EmailSendError(
                f"Отправка письма (from={from_addr}, to={to}) не удалась "
                f"({type(exc).__name__}): {exc}"
            ) from exc
    finally:
        try:
            server.quit()
        except Exception:
            pass
