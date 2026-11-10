"""
Модуль истории загрузок (core.history)

Управляет сохранением, чтением и обновлением списка ранее скачанных медиафайлов.
Данные сохраняются в формате JSON в директории приложения.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from media_downloader.utils import get_base_dir

HISTORY_FILENAME = "download_history.json"


def _get_history_file_path() -> Path:
    """
    Возвращает путь к файлу истории в папке данных приложения.
    """
    base_dir = get_base_dir()
    # Если запущен скомпилированный exe или из пакета, сохраняем рядом с exe/корнем проекта
    if getattr(base_dir, "name", "") in ("media_downloader", "core"):
        target_dir = base_dir.parent
    else:
        target_dir = base_dir

    return target_dir / HISTORY_FILENAME


def load_history() -> List[Dict[str, Any]]:
    """
    Загружает список загрузок из JSON-файла истории.
    Возвращает список словарей отсортированных по дате (свежие сверху).
    """
    path = _get_history_file_path()
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        return []
    return []


def save_history(history_items: List[Dict[str, Any]]) -> None:
    """
    Атомарно и безопасно сохраняет список загрузок в JSON-файл.
    Исключает повреждение файла при аварийном завершении работы ОС или приложения.
    """
    path = _get_history_file_path()
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(history_items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception as err:
        print(f"Ошибка сохранения истории: {err}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def add_history_entry(
    title: str,
    url: str,
    file_path: str,
    format_type: str,
    file_size_str: str = "",
    thumbnail_url: Optional[str] = None,
    extractor: str = "Медиа",
    file_size: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Добавляет новую запись в историю скачиваний.

    :return: Созданная запись.
    """
    history = load_history()

    final_size_str = file_size_str or file_size or kwargs.get("size") or "--"

    entry = {
        "id": f"{int(datetime.now().timestamp() * 1000)}",
        "title": title or "Без названия",
        "url": url or "",
        "file_path": os.path.normpath(file_path) if file_path else "",
        "format_type": format_type or "Медиа",
        "file_size": final_size_str,
        "thumbnail_url": thumbnail_url or kwargs.get("thumb", "") or "",
        "extractor": extractor or "Медиа",
        "timestamp": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

    # Помещаем новую запись в начало списка
    history.insert(0, entry)

    # Ограничиваем историю последними 100 записями
    if len(history) > 100:
        history = history[:100]

    save_history(history)
    return entry


def clear_history() -> None:
    """
    Очищает всю историю загрузок.
    """
    path = _get_history_file_path()
    if path.exists():
        try:
            path.unlink()
        except Exception:
            save_history([])


def delete_history_entry(entry_id: str) -> None:
    """
    Удаляет конкретную запись из истории по её id.
    """
    history = load_history()
    new_history = [item for item in history if item.get("id") != entry_id]
    save_history(new_history)


def clean_missing_history_entries() -> int:
    """
    Удаляет записи файлов, которых больше нет на диске (были удалены или перемещены).
    Возвращает количество удалённых записей.
    """
    history = load_history()
    valid_history = []
    removed_count = 0

    for item in history:
        fpath = item.get("file_path", "")
        if fpath and (os.path.exists(fpath) or os.path.isdir(fpath)):
            valid_history.append(item)
        else:
            removed_count += 1

    if removed_count > 0:
        save_history(valid_history)

    return removed_count
