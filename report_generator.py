"""Генерация отчётов: CSV, HTML и сводка.

Отчёты пишутся в папку Reports. Перемещения кодируются цветом в HTML по
уровню уверенности: high — зелёный, medium — жёлтый, low — красный.
"""

from __future__ import annotations

import csv
import html
import logging
from pathlib import Path
from typing import Dict, List, Optional

from models import DiffResult, ScanError

CONFIDENCE_COLORS = {
    "high": "#d4edda",
    "medium": "#fff3cd",
    "low": "#f8d7da",
}

# Колонки отчёта о перемещениях (разделитель ';').
MOVES_HEADER = [
    "detected_at",
    "root",
    "old_path",
    "new_path",
    "folder_name",
    "confidence",
    "file_count",
]


class ReportGenerator:
    """Создаёт файлы отчётов по результатам сравнения сканов."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------
    def generate_moves_report(self, diff_result: DiffResult, output_path: Path) -> None:
        """CSV только с перемещениями папок.

        Формат: ``detected_at;root;old_path;new_path;folder_name;confidence;file_count``.
        """
        from models import now_str

        detected_at = now_str()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";", lineterminator="\n")
            writer.writerow(MOVES_HEADER)
            for move in diff_result.moved:
                writer.writerow(
                    [
                        detected_at,
                        move.root,
                        move.old_path,
                        move.new_path,
                        move.folder_name,
                        move.confidence,
                        move.file_count,
                    ]
                )

    def generate_csv_report(
        self,
        diff_result: DiffResult,
        errors: List[ScanError],
        output_path: Path,
    ) -> None:
        """Полный CSV-отчёт об изменениях и ошибках."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "change_type",
            "root",
            "relative_path",
            "folder_name",
            "old_path",
            "new_path",
            "old_file_count",
            "new_file_count",
            "confidence",
            "details",
        ]

        with open(output_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";", lineterminator="\n")
            writer.writerow(header)

            for f in diff_result.created:
                writer.writerow(
                    ["folder_created", f.root, f.relative_path, f.folder_name,
                     "", f.relative_path, "", f.file_count, "", ""]
                )

            for f in diff_result.deleted:
                writer.writerow(
                    ["folder_deleted", f.root, f.relative_path, f.folder_name,
                     f.relative_path, "", f.file_count, "", "", ""]
                )

            for m in diff_result.moved:
                writer.writerow(
                    ["folder_moved", m.root, m.new_path, m.folder_name,
                     m.old_path, m.new_path, "", m.file_count, m.confidence, ""]
                )

            for a in diff_result.file_count_decreased:
                writer.writerow(
                    [
                        "folder_file_count_decreased",
                        a.root,
                        a.relative_path,
                        a.folder_name,
                        "",
                        "",
                        a.old_file_count,
                        a.new_file_count,
                        "",
                        f"-{a.decrease_percent:.1f}%",
                    ]
                )

            for e in errors:
                writer.writerow(
                    ["scan_error", "", e.path, "", "", "", "", "", "", e.error]
                )

    # ------------------------------------------------------------------
    # HTML
    # ------------------------------------------------------------------
    def generate_html_report(
        self,
        diff_result: DiffResult,
        errors: List[ScanError],
        scan_info: Optional[Dict],
        output_path: Path,
    ) -> None:
        """Человекочитаемый HTML-отчёт."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        summary = self.generate_summary(scan_info, diff_result)

        parts: List[str] = []
        parts.append("<!DOCTYPE html>")
        parts.append('<html lang="ru"><head><meta charset="utf-8">')
        parts.append("<title>Отчёт мониторинга папок</title>")
        parts.append(
            "<style>"
            "body{font-family:Segoe UI,Arial,sans-serif;margin:2em;color:#222;}"
            "h1,h2{border-bottom:1px solid #ccc;padding-bottom:.3em;}"
            "table{border-collapse:collapse;width:100%;margin:1em 0;}"
            "th,td{border:1px solid #ccc;padding:.4em .6em;text-align:left;"
            "font-size:.9em;word-break:break-all;}"
            "th{background:#f0f0f0;}"
            ".summary{display:flex;gap:2em;flex-wrap:wrap;margin:1em 0;}"
            ".summary div{background:#f8f9fa;border:1px solid #ddd;"
            "padding:.6em 1em;border-radius:6px;}"
            ".high{background:#d4edda;}.medium{background:#fff3cd;}.low{background:#f8d7da;}"
            "</style></head><body>"
        )
        parts.append("<h1>Отчёт мониторинга папок</h1>")

        parts.append("<h2>Сводка</h2>")
        parts.append('<div class="summary">')
        for label, value in summary.items():
            parts.append(f"<div><b>{html.escape(str(label))}</b>: {html.escape(str(value))}</div>")
        parts.append("</div>")

        parts.append("<h2>Перемещения папок</h2>")
        if diff_result.moved:
            parts.append(
                "<table><tr><th>Корень</th><th>Старый путь</th><th>Новый путь</th>"
                "<th>Имя</th><th>Уверенность</th><th>Файлов</th></tr>"
            )
            for m in diff_result.moved:
                cls = m.confidence if m.confidence in CONFIDENCE_COLORS else ""
                parts.append(
                    f'<tr class="{cls}"><td>{html.escape(m.root)}</td>'
                    f"<td>{html.escape(m.old_path)}</td>"
                    f"<td>{html.escape(m.new_path)}</td>"
                    f"<td>{html.escape(m.folder_name)}</td>"
                    f"<td>{html.escape(m.confidence)}</td>"
                    f"<td>{m.file_count}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>Нет перемещений.</p>")

        parts.append("<h2>Папки с аномальным уменьшением файлов</h2>")
        if diff_result.file_count_decreased:
            parts.append(
                "<table><tr><th>Корень</th><th>Путь</th><th>Имя</th>"
                "<th>Было</th><th>Стало</th><th>Уменьшение</th></tr>"
            )
            for a in diff_result.file_count_decreased:
                parts.append(
                    f"<tr><td>{html.escape(a.root)}</td>"
                    f"<td>{html.escape(a.relative_path)}</td>"
                    f"<td>{html.escape(a.folder_name)}</td>"
                    f"<td>{a.old_file_count}</td>"
                    f"<td>{a.new_file_count}</td>"
                    f"<td>-{a.decrease_percent:.1f}%</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>Аномалий не обнаружено.</p>")

        parts.append("<h2>Созданные папки</h2>")
        if diff_result.created:
            parts.append(
                "<table><tr><th>Корень</th><th>Путь</th><th>Имя</th><th>Файлов</th></tr>"
            )
            for f in diff_result.created:
                parts.append(
                    f"<tr><td>{html.escape(f.root)}</td>"
                    f"<td>{html.escape(f.relative_path)}</td>"
                    f"<td>{html.escape(f.folder_name)}</td>"
                    f"<td>{f.file_count}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>Нет созданных папок.</p>")

        parts.append("<h2>Удалённые папки</h2>")
        if diff_result.deleted:
            parts.append(
                "<table><tr><th>Корень</th><th>Путь</th><th>Имя</th><th>Файлов</th></tr>"
            )
            for f in diff_result.deleted:
                parts.append(
                    f"<tr><td>{html.escape(f.root)}</td>"
                    f"<td>{html.escape(f.relative_path)}</td>"
                    f"<td>{html.escape(f.folder_name)}</td>"
                    f"<td>{f.file_count}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>Нет удалённых папок.</p>")

        parts.append("<h2>Ошибки сканирования</h2>")
        if errors:
            parts.append(
                "<table><tr><th>Путь</th><th>Ошибка</th><th>Время</th></tr>"
            )
            for e in errors:
                parts.append(
                    f"<tr><td>{html.escape(e.path)}</td>"
                    f"<td>{html.escape(e.error)}</td>"
                    f"<td>{html.escape(e.timestamp or '')}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p>Ошибок нет.</p>")

        parts.append("</body></html>")

        output_path.write_text("\n".join(parts), encoding="utf-8")

    # ------------------------------------------------------------------
    # Сводка
    # ------------------------------------------------------------------
    def generate_summary(
        self,
        scan_info: Optional[Dict],
        diff_result: DiffResult,
    ) -> Dict[str, int]:
        """Возвращает словарь со сводкой для отчёта."""
        summary: Dict[str, int] = {}

        if scan_info:
            summary["Скан"] = scan_info.get("id", 0)
            summary["Папок просканировано"] = scan_info.get("folder_count", 0)
            summary["Всего файлов"] = scan_info.get("total_file_count", 0)

        summary["Создано папок"] = len(diff_result.created)
        summary["Удалено папок"] = len(diff_result.deleted)
        summary["Перемещено папок"] = len(diff_result.moved)
        summary["Аномалий файлов"] = len(diff_result.file_count_decreased)

        return summary
