"""Настройка импортов для тестов.

Добавляет корень проекта в ``sys.path``, чтобы тесты могли импортировать
модули напрямую (``config_loader``, ``scanner`` и т.д.).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
