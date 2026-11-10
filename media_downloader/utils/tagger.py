"""
Модуль добавления тегов и метаданных в аудиофайлы (tagger.py)
Записывает расширенные метаданные (исполнитель, название, альбом) с помощью библиотеки Mutagen.
"""

import os
from pathlib import Path
from typing import Optional


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
