"""
Модуль вспомогательных функций (utils.py)

Включает:
- Проверку наличия утилиты FFmpeg в системе и локальных каталогах
- Валидацию сетевых URL-адресов
- Определение стандартного пути сохранения файлов в ОС
- Форматирование байтов, скорости передачи данных и временных интервалов
"""

import os
import re
import shutil
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
    return Path(__file__).resolve().parent


def check_ffmpeg_installed() -> bool:
    """
    Проверяет доступность исполняемого файла FFmpeg в системном PATH
    или в директории приложения / поддиректории bin.

    :return: True, если FFmpeg найден и готов к работе, иначе False.
    """
    return get_ffmpeg_path() is not None


def get_ffmpeg_path() -> Optional[str]:
    """
    Определяет абсолютный путь к FFmpeg, если он доступен.
    Проверяет:
    1. Системную переменную PATH
    2. Папку bundle PyInstaller (_MEIPASS)
    3. Папку рядом с .exe или файлами проекта
    4. Подпапку bin/

    :return: Путь к ffmpeg или None, если утилита не найдена.
    """
    # 1. Поиск в системном PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # 2. Локальный поиск в директориях приложения (включая PyInstaller)
    base_dir = get_base_dir()
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else base_dir
    current_file_dir = Path(__file__).resolve().parent

    search_dirs = {base_dir, exe_dir, current_file_dir, current_file_dir.parent}

    for directory in search_dirs:
        candidates = [
            directory / "ffmpeg.exe",
            directory / "ffmpeg",
            directory / "bin" / "ffmpeg.exe",
            directory / "bin" / "ffmpeg",
            directory / "media_downloader" / "bin" / "ffmpeg.exe",
            directory / "media_downloader" / "bin" / "ffmpeg",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

    return None


def get_ffprobe_path() -> Optional[str]:
    """
    Определяет абсолютный путь к ffprobe, если он доступен.
    Используется для проверки медиапотоков и кодеков.
    """
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe

    base_dir = get_base_dir()
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else base_dir
    current_file_dir = Path(__file__).resolve().parent

    search_dirs = {base_dir, exe_dir, current_file_dir, current_file_dir.parent}

    for directory in search_dirs:
        candidates = [
            directory / "ffprobe.exe",
            directory / "ffprobe",
            directory / "bin" / "ffprobe.exe",
            directory / "bin" / "ffprobe",
            directory / "media_downloader" / "bin" / "ffprobe.exe",
            directory / "media_downloader" / "bin" / "ffprobe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)

    return None


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


def format_bytes(bytes_count: Optional[float | int]) -> str:
    """
    Форматирует размер в байтах в человекочитаемый вид (Б, КБ, МБ, ГБ).

    :param bytes_count: Число байтов.
    :return: Строка с числом и единицей измерения.
    """
    if bytes_count is None or bytes_count < 0:
        return "0 Б"

    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    size = float(bytes_count)
    unit_index = 0

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def format_speed(bytes_per_second: Optional[float | int]) -> str:
    """
    Форматирует скорость скачивания (Б/с -> КБ/с, МБ/с).

    :param bytes_per_second: Скорость в байтах в секунду.
    :return: Строка вида "5.24 МБ/с".
    """
    if bytes_per_second is None or bytes_per_second <= 0:
        return "-- МБ/с"
    return f"{format_bytes(bytes_per_second)}/с"


def format_duration(seconds: Optional[float | int]) -> str:
    """
    Преобразует длительность в секундах в формат ЧЧ:ММ:СС или ММ:СС.

    :param seconds: Длительность в секундах.
    :return: Форматированная строка времени.
    """
    if seconds is None or seconds < 0:
        return "Неизвестно"

    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_eta(seconds: Optional[float | int]) -> str:
    """
    Преобразует оставшееся время скачивания (ETA) в строку.

    :param seconds: Количество секунд до завершения.
    :return: Строка времени.
    """
    if seconds is None or seconds < 0:
        return "--:--"
    return format_duration(seconds)


def parse_time_to_seconds(time_str: Optional[str]) -> Optional[float]:
    """
    Преобразует строку времени вида 'ЧЧ:ММ:СС', 'ММ:СС' или 'СС' в секунды.

    :param time_str: Строка с таймкодом (например, '01:30' или '01:15:20').
    :return: Число секунд или None, если строка пуста или некорректна.
    """
    if not time_str or not isinstance(time_str, str):
        return None

    cleaned = time_str.strip()
    if not cleaned:
        return None

    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60.0 + s
        elif len(parts) == 1:
            return float(parts[0])
    except (ValueError, TypeError):
        return None

    return None


def apply_audio_tags(
    file_path: str,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    album: Optional[str] = None,
) -> bool:
    """
    Записывает расширенные метаданные (исполнитель, название, альбом) в аудиофайл
    с помощью библиотеки Mutagen. Поддерживает MP3, M4A, FLAC.

    :param file_path: Путь к аудиофайлу.
    :param artist: Имя исполнителя.
    :param title: Название композиции.
    :param album: Название альбома.
    :return: True в случае успешной записи, иначе False.
    """
    if not file_path or not os.path.exists(file_path):
        return False

    ext = Path(file_path).suffix.lower()
    try:
        if ext == ".mp3":
            from mutagen.easyid3 import EasyID3
            from mutagen.mp3 import MP3
            try:
                audio = EasyID3(file_path)
            except Exception:
                try:
                    mp3_obj = MP3(file_path)
                    mp3_obj.add_tags()
                    mp3_obj.save()
                    audio = EasyID3(file_path)
                except Exception:
                    return False
            if artist:
                audio["artist"] = [artist]
            if title:
                audio["title"] = [title]
            if album:
                audio["album"] = [album]
            audio.save()
            return True
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            audio = MP4(file_path)
            if artist:
                audio["\xa9ART"] = [artist]
            if title:
                audio["\xa9nam"] = [title]
            if album:
                audio["\xa9alb"] = [album]
            audio.save()
            return True
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            if artist:
                audio["artist"] = [artist]
            if title:
                audio["title"] = [title]
            if album:
                audio["album"] = [album]
            audio.save()
            return True
    except Exception as exc:
        print(f"[!] Не удалось обновить метаданные mutagen: {exc}")
        return False

    return False


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

