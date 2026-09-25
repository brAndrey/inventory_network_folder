"""Принудительная отправка последнего отчёта по e-mail.

Находит самый свежий отчёт в папке ``Reports`` и отправляет его на адрес из
секции ``[ALERTS]`` конфигурации независимо от того, были ли изменения.

Запуск:

    python send_report.py
    run_send_report.bat
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List

from config_loader import ConfigLoader, build_paths
from email_sender import EmailSendError, send_email, smtp_credentials
from logger_setup import setup_logger

# Коды завершения.
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NO_REPORT = 2
EXIT_SEND_ERROR = 3

REPORT_HTML_PREFIX = "report_"
REPORT_HTML_SUFFIX = ".html"


def find_last_report_attachments(report_dir: Path) -> List[Path]:
    """Возвращает файлы последнего отчёта (HTML + связанные CSV) или [].

    Последним считается HTML-отчёт с максимальной меткой времени в имени файла
    (``report_YYYYMMDD_HHMMSS.html``). Вместе с ним прикладываются одноимённые
    CSV-отчёты, если они существуют.
    """
    report_dir = Path(report_dir)
    if not report_dir.is_dir():
        return []

    html_files = sorted(report_dir.glob(f"{REPORT_HTML_PREFIX}*{REPORT_HTML_SUFFIX}"))
    if not html_files:
        return []

    latest_html = html_files[-1]
    name = latest_html.name
    timestamp = name[len(REPORT_HTML_PREFIX):-len(REPORT_HTML_SUFFIX)]

    attachments: List[Path] = [latest_html]
    for related in (f"report_{timestamp}.csv", f"moves_{timestamp}.csv"):
        candidate = report_dir / related
        if candidate.is_file():
            attachments.append(candidate)

    return attachments


def main() -> int:
    """Точка входа принудительной отправки последнего отчёта."""
    base_dir = Path(__file__).resolve().parent

    # Базовый консольный логгер на случай ошибок чтения конфига.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("folder_monitor")

    loader = ConfigLoader(base_dir)
    try:
        _, raw_options = loader.load()
        alerts = loader.load_alerts()
    except Exception as exc:
        logger.error(f"Ошибка загрузки конфигурации: {exc}")
        return EXIT_CONFIG_ERROR

    paths = build_paths(base_dir, raw_options)
    logger = setup_logger(paths.log_dir)

    if not loader.parse_bool(alerts.get("enabled"), False):
        logger.error("[ALERTS] выключены — принудительная отправка невозможна.")
        return EXIT_CONFIG_ERROR

    email_to = alerts.get("email_to", "").strip()
    if not email_to:
        logger.error("[ALERTS] включены, но email_to не задан.")
        return EXIT_CONFIG_ERROR

    smtp_server = alerts.get("smtp_server", "").strip()
    if not smtp_server:
        logger.error("[ALERTS] включены, но smtp_server не задан.")
        return EXIT_CONFIG_ERROR

    attachments = find_last_report_attachments(paths.report_dir)
    if not attachments:
        logger.error(f"В {paths.report_dir} не найдено ни одного отчёта (report_*.html).")
        return EXIT_NO_REPORT

    logger.info(f"Последний отчёт: {attachments[0].name}")
    for extra in attachments[1:]:
        logger.info(f"  + вложение: {extra.name}")

    smtp_port = loader.parse_int(alerts.get("smtp_port"), 587)
    from_addr = alerts.get("email_from", email_to).strip() or email_to
    smtp_user, smtp_password = smtp_credentials(alerts)

    timestamp = attachments[0].stem[len(REPORT_HTML_PREFIX):]
    subject = f"Мониторинг папок: отчёт {timestamp}"
    body_lines = [
        "Принудительная отправка последнего отчёта мониторинга папок.",
        "",
        "Приложенные файлы:",
    ]
    body_lines.extend(f"  - {p.name}" for p in attachments)
    body = "\n".join(body_lines)

    try:
        send_email(
            to=email_to,
            subject=subject,
            body=body,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            from_addr=from_addr,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            attachments=attachments,
        )
    except EmailSendError as exc:
        logger.exception("Не удалось отправить отчёт на %s: %s", email_to, exc)
        return EXIT_SEND_ERROR

    logger.info(f"Отчёт отправлен на {email_to}: {subject}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
