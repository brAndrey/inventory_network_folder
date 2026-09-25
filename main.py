"""Точка входа мониторинга сетевых папок.

Оркестрирует: загрузку конфигурации, инициализацию БД, защиту от повторного
запуска, сканирование, сравнение с предыдущим сканом, генерацию отчётов и
очистку старых данных.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from cleanup import CleanupService
from config_loader import ConfigLoader, build_paths
from database import (
    DatabaseManager,
    ErrorRepository,
    EventRepository,
    FolderRepository,
    MoveRepository,
    ScanRepository,
)
from diff_engine import DiffEngine
from email_sender import EmailSendError, send_email, smtp_credentials
from logger_setup import setup_logger
from models import DiffResult, MonitorPaths, RootConfig
from report_generator import ReportGenerator
from scanner import FolderScanner, ScanTimeoutError

# Коды завершения.
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_DB_ERROR = 2
EXIT_TIMEOUT = 3
EXIT_SCAN_ERROR = 4

# Зависшим считается скан со статусом 'running' старше этого числа часов.
STALE_RUNNING_HOURS = 2


class MonitorApp:
    """Основной класс приложения."""

    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.config_loader = ConfigLoader(self.base_dir)

        # Базовый консольный логгер на случай ошибок чтения конфига.
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.logger = logging.getLogger("folder_monitor")

        self.paths: Optional[MonitorPaths] = None
        self.options: Dict = {}
        self.alerts: Dict = {}
        self.db_manager: Optional[DatabaseManager] = None

        self.scan_repo: Optional[ScanRepository] = None
        self.folder_repo: Optional[FolderRepository] = None
        self.event_repo: Optional[EventRepository] = None
        self.error_repo: Optional[ErrorRepository] = None
        self.move_repo: Optional[MoveRepository] = None

    # ------------------------------------------------------------------
    # Главный цикл
    # ------------------------------------------------------------------
    def run(self) -> int:
        """Запускает полный цикл мониторинга и возвращает код завершения."""
        roots = self._load_config()
        if roots is None:
            return EXIT_CONFIG_ERROR

        self.logger.info("=== Начало мониторинга папок ===")
        self.logger.info(f"Корней для сканирования: {len(roots)}")
        for rc in roots:
            self.logger.info(f"  {rc.path} (глубина {rc.max_depth})")

        if not self._init_database():
            return EXIT_DB_ERROR

        if self._check_duplicate_run():
            return EXIT_OK

        scan_id = self._start_scan(roots)
        if scan_id is None:
            return EXIT_DB_ERROR

        scan_code = self._execute_scan(roots, scan_id)

        if scan_code == EXIT_TIMEOUT:
            self._cleanup()
            return EXIT_TIMEOUT

        if scan_code == EXIT_SCAN_ERROR:
            self._cleanup()
            return EXIT_SCAN_ERROR

        # Сравнение с предыдущим завершённым сканом.
        prev_scan_id = self.scan_repo.get_previous_completed_scan(scan_id)
        diff: Optional[DiffResult] = None
        if prev_scan_id is None:
            self.logger.info("Первый скан, сравнение не выполняется")
        else:
            diff = self._compare_with_previous(prev_scan_id, scan_id)

        self._generate_reports(scan_id, diff)
        self._send_alert_email(diff, scan_id)

        self._cleanup()
        self.logger.info("=== Мониторинг завершён ===")
        return EXIT_OK

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------
    def _load_config(self) -> Optional[List[RootConfig]]:
        """Загружает конфигурацию и возвращает корни (None при ошибке)."""
        try:
            roots, raw_options = self.config_loader.load()
        except Exception as exc:
            self.logger.error(f"Ошибка загрузки конфигурации: {exc}")
            return None

        if not roots:
            self.logger.error("В конфигурации не найдены корни (секция [ROOTS]).")
            return None

        self.options = self._parse_options(raw_options)
        self.alerts = self.config_loader.load_alerts()
        self.paths = build_paths(self.base_dir, raw_options)

        # Полноценный логгер (консоль + файл).
        self.logger = setup_logger(self.paths.log_dir)
        self.logger.info(f"Конфигурация: {self.config_loader.config_path}")

        return roots

    def _parse_options(self, raw_options: Dict[str, str]) -> Dict:
        """Преобразует сырые строковые опции в типизированные."""
        return {
            "retention_days": self.config_loader.parse_int(
                raw_options.get("retention_days"), 7
            ),
            "file_count_decrease_percent": float(
                self.config_loader.parse_int(
                    raw_options.get("file_count_decrease_percent"), 20
                )
            ),
            "file_count_decrease_min": self.config_loader.parse_int(
                raw_options.get("file_count_decrease_min"), 10
            ),
            "scan_timeout_minutes": self.config_loader.parse_int(
                raw_options.get("scan_timeout_minutes"), 55
            ),
            "count_hidden_files": self.config_loader.parse_bool(
                raw_options.get("count_hidden_files"), True
            ),
        }

    # ------------------------------------------------------------------
    # БД
    # ------------------------------------------------------------------
    def _init_database(self) -> bool:
        """Создаёт соединение и схему БД."""
        try:
            self.db_manager = DatabaseManager(self.paths.db_path)
            self.db_manager.create_schema()
        except Exception as exc:
            self.logger.error(f"Ошибка инициализации базы данных: {exc}")
            return False

        self.scan_repo = ScanRepository(self.db_manager)
        self.folder_repo = FolderRepository(self.db_manager)
        self.event_repo = EventRepository(self.db_manager)
        self.error_repo = ErrorRepository(self.db_manager)
        self.move_repo = MoveRepository(self.db_manager)
        return True

    # ------------------------------------------------------------------
    # Защита от повторного запуска
    # ------------------------------------------------------------------
    def _check_duplicate_run(self) -> bool:
        """Защита от параллельного запуска и зависших процессов.

        Возвращает True, если новый скан запускать нельзя (есть незавершённый
        скан). Для сканов старше ``STALE_RUNNING_HOURS`` дополнительно пишется
        событие ``timeout_warning``.
        """
        running_ids = self.scan_repo.get_running_scans()
        if not running_ids:
            return False

        stale_ids = self.scan_repo.get_running_scans_older_than(STALE_RUNNING_HOURS)
        for rid in stale_ids:
            self.event_repo.add_event(
                rid,
                "timeout_warning",
                details=json.dumps(
                    {"message": f"Скан выполняется дольше {STALE_RUNNING_HOURS} ч"}
                ),
            )

        self.logger.warning(
            "Обнаружен незавершённый скан (running): %s. Новый скан не запускается.",
            running_ids,
        )
        return True

    # ------------------------------------------------------------------
    # Сканирование
    # ------------------------------------------------------------------
    def _start_scan(self, roots: List[RootConfig]) -> Optional[int]:
        """Создаёт запись скана со статусом 'running'."""
        try:
            snapshot = self.config_loader.get_config_snapshot()
            scan_id = self.scan_repo.start_scan(snapshot)
        except Exception as exc:
            self.logger.error(f"Не удалось создать запись скана: {exc}")
            return None

        self.event_repo.add_event(
            scan_id,
            "scan_started",
            details=json.dumps({"roots": [r.path for r in roots]}),
        )
        self.logger.info(f"Начат скан #{scan_id}")
        return scan_id

    def _execute_scan(self, roots: List[RootConfig], scan_id: int) -> int:
        """Сканирует все корни и сохраняет результат. Возвращает код завершения."""
        scanner = FolderScanner(self.options, self.logger)
        timeout_seconds = self.options["scan_timeout_minutes"] * 60
        deadline = time.monotonic() + timeout_seconds

        all_folders = []
        all_errors = []
        total_file_count = 0

        try:
            for rc in roots:
                self.logger.info(
                    f"Сканирование корня: {rc.path} (глубина {rc.max_depth})"
                )
                result = scanner.scan_root(rc, scan_id, deadline=deadline)
                all_folders.extend(result.folders)
                all_errors.extend(result.errors)
                total_file_count += result.total_file_count
                self.logger.info(
                    f"Корень {rc.path}: папок {result.folder_count}, "
                    f"ошибок {len(result.errors)}"
                )

        except ScanTimeoutError as exc:
            partial = exc.partial_result
            if partial is not None:
                all_folders.extend(partial.folders)
                all_errors.extend(partial.errors)
                total_file_count += partial.total_file_count
            self._save_scan_data(scan_id, all_folders, all_errors, total_file_count)
            self.scan_repo.finish_scan(
                scan_id, "timeout", len(all_folders), total_file_count
            )
            self.event_repo.add_event(
                scan_id,
                "scan_timeout",
                details=json.dumps({"timeout_minutes": self.options["scan_timeout_minutes"]}),
            )
            self.logger.warning("Сканирование прервано по таймауту, сохранены частичные данные.")
            return EXIT_TIMEOUT

        except Exception as exc:
            self.logger.exception(f"Критическая ошибка сканирования: {exc}")
            self._save_scan_data(scan_id, all_folders, all_errors, total_file_count)
            self.scan_repo.finish_scan(
                scan_id, "failed", len(all_folders), total_file_count
            )
            self.event_repo.add_event(
                scan_id,
                "scan_failed",
                details=json.dumps({"error": str(exc)}),
            )
            return EXIT_SCAN_ERROR

        # Успешное завершение.
        self._save_scan_data(scan_id, all_folders, all_errors, total_file_count)
        self.scan_repo.finish_scan(
            scan_id, "completed", len(all_folders), total_file_count
        )
        self.event_repo.add_event(
            scan_id,
            "scan_completed",
            details=json.dumps(
                {
                    "folder_count": len(all_folders),
                    "total_file_count": total_file_count,
                }
            ),
        )
        self.logger.info(
            f"Скан #{scan_id} завершён: папок {len(all_folders)}, "
            f"файлов {total_file_count}, ошибок {len(all_errors)}"
        )
        return EXIT_OK

    def _save_scan_data(self, scan_id: int, folders, errors, total_file_count: int) -> None:
        """Сохраняет папки и ошибки скана в БД."""
        self.folder_repo.insert_folders_batch(scan_id, folders)

        for err in errors:
            self.error_repo.add_error(scan_id, err.path, err.error)
            # Значимые события дублируем в events.
            self.event_repo.add_event(
                scan_id,
                "permission_denied",
                root=None,
                old_path=None,
                new_path=err.path,
                details=json.dumps({"error": err.error}),
            )

    # ------------------------------------------------------------------
    # Сравнение
    # ------------------------------------------------------------------
    def _compare_with_previous(
        self,
        prev_scan_id: int,
        new_scan_id: int,
    ) -> DiffResult:
        """Сравнивает сканы и сохраняет события/перемещения в БД."""
        engine = DiffEngine(self.db_manager, self.logger)
        diff = engine.compare_scans(prev_scan_id, new_scan_id, self.options)

        for f in diff.created:
            self.event_repo.add_event(
                new_scan_id,
                "folder_created",
                root=f.root,
                new_path=f.relative_path,
                details=json.dumps(
                    {"folder_name": f.folder_name, "file_count": f.file_count}
                ),
            )

        for f in diff.deleted:
            self.event_repo.add_event(
                new_scan_id,
                "folder_deleted",
                root=f.root,
                old_path=f.relative_path,
                details=json.dumps(
                    {"folder_name": f.folder_name, "file_count": f.file_count}
                ),
            )

        for m in diff.moved:
            self.event_repo.add_event(
                new_scan_id,
                "folder_moved",
                root=m.root,
                old_path=m.old_path,
                new_path=m.new_path,
                details=json.dumps(
                    {
                        "folder_name": m.folder_name,
                        "confidence": m.confidence,
                        "file_count": m.file_count,
                    }
                ),
            )
            self.move_repo.add_move(
                new_scan_id,
                m.root,
                m.old_path,
                m.new_path,
                m.folder_name,
                m.confidence,
                m.file_count,
            )

        for a in diff.file_count_decreased:
            self.event_repo.add_event(
                new_scan_id,
                "folder_file_count_decreased",
                root=a.root,
                old_path=a.relative_path,
                details=json.dumps(
                    {
                        "folder_name": a.folder_name,
                        "old_file_count": a.old_file_count,
                        "new_file_count": a.new_file_count,
                        "decrease_percent": a.decrease_percent,
                    }
                ),
            )

        self.logger.info(
            f"Сравнение #{prev_scan_id} -> #{new_scan_id}: создано "
            f"{len(diff.created)}, удалено {len(diff.deleted)}, перемещено "
            f"{len(diff.moved)}, аномалий {len(diff.file_count_decreased)}"
        )
        return diff

    # ------------------------------------------------------------------
    # Отчёты
    # ------------------------------------------------------------------
    def _generate_reports(self, scan_id: int, diff: Optional[DiffResult]) -> None:
        """Создаёт CSV и HTML отчёты в папке Reports."""
        try:
            self.paths.report_dir.mkdir(parents=True, exist_ok=True)

            scan_info_row = self.scan_repo.get_scan_info(scan_id)
            scan_info = dict(scan_info_row) if scan_info_row is not None else {}
            errors = self.error_repo.get_errors_by_scan(scan_id)

            diff = diff or DiffResult()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            generator = ReportGenerator(self.logger)
            generator.generate_csv_report(
                diff, errors, self.paths.report_dir / f"report_{timestamp}.csv"
            )
            generator.generate_html_report(
                diff,
                errors,
                scan_info,
                self.paths.report_dir / f"report_{timestamp}.html",
            )
            generator.generate_moves_report(
                diff, self.paths.report_dir / f"moves_{timestamp}.csv"
            )
            self.logger.info(f"Отчёты сохранены в {self.paths.report_dir}")

        except Exception as exc:
            self.logger.error(f"Не удалось сгенерировать отчёты: {exc}")

    # ------------------------------------------------------------------
    # Оповещения
    # ------------------------------------------------------------------
    def _alerts_enabled(self) -> bool:
        """True, если секция [ALERTS] включена (enabled = true)."""
        return self.config_loader.parse_bool(self.alerts.get("enabled"), False)

    @staticmethod
    def _has_alertable_changes(diff: DiffResult) -> bool:
        """True, если есть изменения, требующие оповещения.

        Оповещение необходимо только при перемещении, удалении папки или
        аномальном уменьшении количества файлов.
        """
        return bool(diff.moved or diff.deleted or diff.file_count_decreased)

    @staticmethod
    def _display_path(root: str, relative_path: str) -> str:
        """Склеивает корень и относительный путь для отображения в письме."""
        if not relative_path:
            return root
        return f"{root}\\{relative_path.replace('/', '\\')}"

    @staticmethod
    def _build_email_subject(diff: DiffResult, scan_id: int) -> str:
        """Тема письма с краткой сводкой изменений."""
        parts = []
        if diff.moved:
            parts.append(f"перемещено {len(diff.moved)}")
        if diff.deleted:
            parts.append(f"удалено {len(diff.deleted)}")
        if diff.file_count_decreased:
            parts.append(f"аномалий {len(diff.file_count_decreased)}")
        summary = ", ".join(parts) if parts else "без изменений"
        return f"Мониторинг папок: скан #{scan_id} — {summary}"

    @staticmethod
    def _build_email_body(diff: DiffResult, scan_id: int) -> str:
        """Тело письма с деталями изменений."""
        lines = [f"Скан #{scan_id}. Обнаружены изменения:"]

        if diff.moved:
            lines.append("")
            lines.append(f"Перемещённые папки ({len(diff.moved)}):")
            for m in diff.moved:
                old = MonitorApp._display_path(m.root, m.old_path)
                new = MonitorApp._display_path(m.root, m.new_path)
                lines.append(
                    f"  - {m.folder_name}: {old} -> {new} "
                    f"(уверенность: {m.confidence}, файлов: {m.file_count})"
                )

        if diff.deleted:
            lines.append("")
            lines.append(f"Удалённые папки ({len(diff.deleted)}):")
            for f in diff.deleted:
                path = MonitorApp._display_path(f.root, f.relative_path)
                lines.append(f"  - {f.folder_name}: {path} (файлов: {f.file_count})")

        if diff.file_count_decreased:
            lines.append("")
            lines.append(
                f"Аномальное уменьшение файлов ({len(diff.file_count_decreased)}):"
            )
            for a in diff.file_count_decreased:
                path = MonitorApp._display_path(a.root, a.relative_path)
                lines.append(
                    f"  - {a.folder_name}: {path} — было {a.old_file_count}, "
                    f"стало {a.new_file_count} (-{a.decrease_percent:.1f}%)"
                )

        return "\n".join(lines)

    def _smtp_credentials(self) -> tuple:
        """Возвращает (пользователь, пароль) для SMTP-авторизации.

        Делегирует в :func:`email_sender.smtp_credentials`.
        """
        return smtp_credentials(self.alerts)

    def _send_alert_email(self, diff: Optional[DiffResult], scan_id: int) -> None:
        """Отправляет письмо только при значимых изменениях (секция [ALERTS]).

        Письмо отправляется, если есть перемещённые, удалённые папки или папки
        с аномальным уменьшением количества файлов. Итог (отправлено или нет)
        всегда фиксируется в логе.
        """
        if not self._alerts_enabled():
            self.logger.info("[ALERTS] выключены — отчёт по e-mail не отправляется.")
            return

        if diff is None or not self._has_alertable_changes(diff):
            self.logger.info(
                "Изменений, требующих оповещения, нет — отчёт по e-mail не отправляется."
            )
            return

        email_to = self.alerts.get("email_to", "")
        if not email_to:
            self.logger.warning("[ALERTS] включены, но email_to не задан — отчёт не отправляется.")
            return

        smtp_server = self.alerts.get("smtp_server", "")
        if not smtp_server:
            self.logger.warning("[ALERTS] включены, но smtp_server не задан — отчёт не отправляется.")
            return

        subject = self._build_email_subject(diff, scan_id)
        body = self._build_email_body(diff, scan_id)
        smtp_port = self.config_loader.parse_int(self.alerts.get("smtp_port"), 587)
        smtp_user, smtp_password = self._smtp_credentials()

        try:
            send_email(
                to=email_to,
                subject=subject,
                body=body,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                from_addr=self.alerts.get("email_from", email_to),
                smtp_user=smtp_user,
                smtp_password=smtp_password,
            )
            self.logger.info(f"Отчёт по e-mail отправлен на {email_to}: {subject}")
        except EmailSendError as exc:
            self.logger.exception("Не удалось отправить отчёт по e-mail: %s", exc)

    # ------------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------------
    def _cleanup(self) -> None:
        """Удаляет старые сканы и выполняет VACUUM не чаще раза в сутки."""
        try:
            cleanup = CleanupService(self.db_manager, self.logger)
            cleanup.delete_old_scans(self.options.get("retention_days", 7))
            cleanup.vacuum_database()
        except Exception as exc:
            self.logger.warning(f"Ошибка очистки: {exc}")
        finally:
            if self.db_manager is not None:
                self.db_manager.close()


def main() -> int:
    """Точка входа."""
    app = MonitorApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
