"""
Модуль поиска и валидации FFmpeg и FFprobe (ffmpeg.py)
"""

import shutil
import sys
from pathlib import Path
from typing import Optional

from media_downloader.utils.system import get_base_dir


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

    search_dirs = {base_dir, exe_dir, current_file_dir, current_file_dir.parent, current_file_dir.parent.parent}

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

    search_dirs = {base_dir, exe_dir, current_file_dir, current_file_dir.parent, current_file_dir.parent.parent}

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
