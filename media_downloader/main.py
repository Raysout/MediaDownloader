"""
Главный модуль запуска приложения Media Downloader (main.py)
"""

import sys
from pathlib import Path

# Добавляем родительскую директорию в sys.path для корректных относительных импортов
current_file = Path(__file__).resolve()
parent_dir = current_file.parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


def main():
    """
    Точка входа: запуск приложения Media Downloader Pro на PyQt6.
    """
    from media_downloader.qt_gui import main as qt_main
    qt_main()


if __name__ == "__main__":
    main()
