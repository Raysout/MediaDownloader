"""
Системные утилиты и файловые операции (system.py)
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


def get_base_dir() -> Path:
    """
    Возвращает базовую директорию приложения.
    Корректно обрабатывает запуск как из исходного кода, так и из скомпилированного .exe (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(sys.executable).resolve().parent
    # __file__ is in media_downloader/utils/system.py -> parent.parent is media_downloader/
    return Path(__file__).resolve().parent.parent


def is_valid_url(url: str) -> bool:
    """
    Проверяет корректность переданной ссылки.

    :param url: Строка с веб-адресом.
    :return: True, если строка имеет схему http/https и сетевой хост.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def get_default_download_dir() -> str:
    """
    Возвращает стандартную папку для загрузок пользователя в зависимости от ОС.
    По умолчанию: ~/Downloads (Загрузки).
    Если директория не существует, возвращается домашняя папка.

    :return: Строка с абсолютным путем к директории загрузок.
    """
    downloads = Path.home() / "Downloads"
    if downloads.exists() and downloads.is_dir():
        return str(downloads)
    return str(Path.home())


def sanitize_filename(name: str, max_length: int = 200) -> str:
    r"""
    Очищает имя файла от недопустимых символов Windows и UNIX.
    Удаляет запрещенные символы (<, >, :, ", /, \, |, ?, *), управляющие символы,
    лишние пробелы и точки на конце, а также предотвращает зарезервированные имена DOS (CON, PRN, etc.).
    """
    if not name or not isinstance(name, str):
        return "downloaded_file"

    # Удаляем непечатаемые и управляющие символы
    clean = "".join(c for c in name if c.isprintable() and ord(c) >= 32)

    # Заменяем запрещенные символы Windows на знак подчеркивания
    clean = re.sub(r'[\\/*?:"<>|]', "_", clean)

    # Убираем повторяющиеся подчеркивания/пробелы
    clean = re.sub(r"\s+", " ", clean).strip(". ")

    if not clean:
        clean = "downloaded_file"

    # Ограничение длины имени файла
    if len(clean) > max_length:
        clean = clean[:max_length].rstrip(". ")

    # Защита от зарезервированных имен устройств Windows
    stem = clean.split(".")[0].upper()
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if stem in reserved:
        clean = f"_{clean}"

    return clean


def get_system_clipboard_text() -> str:
    """
    Безопасно и мгновенно считывает текст из системного буфера обмена.
    В Windows использует прямой Win32 API через ctypes (0 утечек дескрипторов GDI/User и без Tkinter).
    Корректно работает в 64-битных и 32-битных версиях Python.
    """
    # 1. Пробуем через активное приложение Qt (если доступно)
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            cb = app.clipboard()
            if cb:
                txt = cb.text()
                if txt:
                    return txt
    except Exception:
        pass

    # 2. Прямой 64-бит Win32 API с полными типами аргументов
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            CF_UNICODETEXT = 13

            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.GetClipboardData.argtypes = [wintypes.UINT]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

            if user32.OpenClipboard(None):
                try:
                    handle = user32.GetClipboardData(CF_UNICODETEXT)
                    if handle:
                        pointer = kernel32.GlobalLock(handle)
                        if pointer:
                            try:
                                text = ctypes.c_wchar_p(pointer).value or ""
                                return text
                            finally:
                                kernel32.GlobalUnlock(handle)
                finally:
                    user32.CloseClipboard()
        except Exception:
            pass

    # 3. Fallback для Tkinter (если доступен)
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        txt = r.clipboard_get()
        r.destroy()
        return str(txt) if txt else ""
    except Exception:
        return ""


def choose_directory(initial_dir: Optional[str] = None) -> Optional[str]:
    """
    Открывает нативный системный диалог выбора папки.
    Сначала пробует Tkinter с поднятием окна (-topmost),
    затем использует нативный PowerShell Windows FolderBrowserDialog.
    """
    init_path = (
        os.path.abspath(initial_dir)
        if initial_dir and os.path.exists(initial_dir)
        else os.path.abspath(get_default_download_dir())
    )

    # 1. Tkinter с принудительным поднятием поверх окна приложения
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        res = filedialog.askdirectory(parent=root, initialdir=init_path, title="Выберите папку для сохранения")
        root.destroy()
        if res:
            return os.path.normpath(res)
    except Exception:
        pass

    # 2. Нативный PowerShell Windows диалог выбора папки (надежный fallback)
    if sys.platform == "win32":
        try:
            import subprocess
            ps_code = f"""
            [System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'Выберите папку для сохранения'
            $dialog.SelectedPath = '{init_path}'
            $dialog.ShowNewFolderButton = $true
            if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
                Write-Output $dialog.SelectedPath
            }}
            """
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_code],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=False,
            )
            out = proc.stdout.strip()
            if out and os.path.isdir(out):
                return os.path.normpath(out)
        except Exception:
            pass

    return None
