"""
Фасад обратной совместимости для истории загрузок (history.py).
Реэкспортирует функции и константы из media_downloader.core.history.
"""

from media_downloader.core.history import (
    HISTORY_FILENAME,
    load_history,
    save_history,
    add_history_entry,
    clear_history,
    delete_history_entry,
    clean_missing_history_entries,
)

__all__ = [
    "HISTORY_FILENAME",
    "load_history",
    "save_history",
    "add_history_entry",
    "clear_history",
    "delete_history_entry",
    "clean_missing_history_entries",
]
