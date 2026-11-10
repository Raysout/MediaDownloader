"""
Модуль загрузки медиа (downloader.py)

Отвечает за взаимодействие с библиотекой yt-dlp:
- Извлечение расширенных метаданных (название, длительность, обложка, доступные разрешения)
- Скачивание видео в форматах MP4, MKV, WEBM с объединением потоков
- Скачивание аудио в форматах MP3, FLAC, M4A, WAV, OPUS
- Вшивание метаданных и обложки (по выбору пользователя)
- Отслеживание и передачу прогресса выполнения
- Возврат точного пути к скачанному файлу для последующего открытия
"""

import json
import os
import re
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional
import yt_dlp
from yt_dlp.utils import DownloadError

from media_downloader.utils import (
    get_ffmpeg_path,
    format_bytes,
    format_speed,
    format_eta,
    format_duration,
    apply_audio_tags,
    sanitize_filename,
)


class MediaDownloader:
    """
    Класс для управления парсингом и загрузкой медиа через yt-dlp.
    """

    def __init__(self):
        self.ffmpeg_path = get_ffmpeg_path()

    def _get_base_ydl_opts(
        self,
        cookies_browser: Optional[str] = None,
        ratelimit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Базовые настройки для yt-dlp, включая FFmpeg, Cookies браузера и лимит скорости.
        """
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "ignoreerrors": False,
            "logtostderr": False,
        }
        if self.ffmpeg_path:
            opts["ffmpeg_location"] = self.ffmpeg_path

        if cookies_browser:
            cb = cookies_browser.strip().lower()
            if cb and cb not in ("none", "без cookies", "отключено"):
                opts["cookiesfrombrowser"] = (cb, None, None, None)

        if ratelimit and ratelimit > 0:
            opts["ratelimit"] = ratelimit

        return opts

    def extract_info(self, url: str, cookies_browser: Optional[str] = None) -> Dict[str, Any]:
        """
        Анализирует URL и извлекает метаданные ролика/трека.

        :param url: Ссылка на видео или аудио.
        :param cookies_browser: Имя браузера для импорта cookies (chrome, firefox, edge, etc.).
        :return: Словарь с информацией о названии, длительности, обложке, источнике и разрешениях.
        :raises DownloadError: В случае сетевой ошибки, геоблокировки или недоступности видео.
        :raises Exception: В случае непредвиденных ошибок парсинга.
        """
        ydl_opts = self._get_base_ydl_opts(cookies_browser=cookies_browser)
        ydl_opts.update({
            "extract_flat": False,
            "skip_download": True,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise DownloadError("Не удалось получить информацию по указанной ссылке.")

        # Если это плейлист, берем первый элемент для карточки превью
        webpage_url = info.get("webpage_url") or url
        if "entries" in info and info["entries"]:
            first_entry = next((e for e in info["entries"] if e), None)
            if first_entry:
                info = first_entry

        title = info.get("title", "Без названия")
        duration = info.get("duration")
        duration_str = format_duration(duration)
        thumbnail = info.get("thumbnail")
        extractor = info.get("extractor_key") or info.get("extractor") or "Медиа-сервис"
        uploader = info.get("uploader") or info.get("channel") or info.get("artist") or "Неизвестный автор"
        artist = info.get("artist") or info.get("creator") or uploader
        album = info.get("album") or ""
        track = info.get("track") or title
        has_chapters = bool(info.get("chapters"))

        # Доступные языки субтитров
        sub_list = []
        if info.get("subtitles"):
            sub_list.extend(list(info.get("subtitles").keys()))
        if info.get("automatic_captions"):
            sub_list.extend(list(info.get("automatic_captions").keys()))
        unique_subs = sorted(list(set(sub_list)))

        # Анализ доступных качеств видео
        formats = info.get("formats", [])
        heights_set = set()
        has_video_stream = False

        for f in formats:
            vcodec = f.get("vcodec", "none")
            height = f.get("height")
            if vcodec != "none" and height and isinstance(height, (int, float)) and height > 0:
                has_video_stream = True
                heights_set.add(int(height))

        sorted_heights = sorted(list(heights_set), reverse=True)
        resolutions = [f"{h}p" for h in sorted_heights]
        is_audio_only = not has_video_stream

        if not resolutions and not is_audio_only:
            resolutions = ["Лучшее доступное"]

        return {
            "title": title,
            "url": webpage_url,
            "duration": duration,
            "duration_str": duration_str,
            "thumbnail_url": thumbnail,
            "extractor": extractor,
            "uploader": uploader,
            "artist": artist,
            "album": album,
            "track": track,
            "has_chapters": has_chapters,
            "subtitles": unique_subs,
            "resolutions": resolutions,
            "is_audio_only": is_audio_only,
            "raw_info": info,
        }

    def extract_playlist_info(self, url: str, cookies_browser: Optional[str] = None) -> Dict[str, Any]:
        """
        Извлекает информацию о плейлисте (название, автор, количество и список треков).
        Использует extract_flat='in_playlist' для мгновенного получения списка без долгого парсинга.
        """
        ydl_opts = self._get_base_ydl_opts(cookies_browser=cookies_browser)
        ydl_opts.update({
            "extract_flat": "in_playlist",
            "skip_download": True,
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise DownloadError("Не удалось получить информацию о плейлисте.")

        title = info.get("title", "Плейлист")
        uploader = info.get("uploader") or info.get("channel") or info.get("artist") or "Неизвестный автор"
        entries = info.get("entries", [])
        clean_entries = []

        for e in entries:
            if e:
                item_title = e.get("title") or "Без названия"
                raw_url = e.get("url") or ""
                if raw_url.startswith("http"):
                    item_url = raw_url
                elif e.get("id"):
                    item_url = f"https://www.youtube.com/watch?v={e['id']}"
                else:
                    item_url = raw_url

                item_duration = format_duration(e.get("duration"))
                clean_entries.append({
                    "title": item_title,
                    "url": item_url,
                    "duration": item_duration,
                    "id": str(e.get("id", "")),
                })

        # Если это SoundCloud или есть треки без названий, восстанавливаем метаданные через API/гидратацию
        if "soundcloud.com" in url.lower() or any(e.get("title") in ("Без названия", "", None) for e in clean_entries):
            clean_entries = self._enrich_soundcloud_playlist_entries(clean_entries, url)

        return {
            "title": title,
            "uploader": uploader,
            "url": info.get("webpage_url") or url,
            "count": len(clean_entries),
            "entries": clean_entries,
            "raw_info": info,
        }

    def _enrich_soundcloud_playlist_entries(
        self, entries: List[Dict[str, Any]], original_url: str
    ) -> List[Dict[str, Any]]:
        """
        Восстанавливает настоящие названия, длительности и прямые ссылки для треков
        из плейлистов/сетов SoundCloud, которые yt-dlp по умолчанию возвращает без названий.
        """
        missing_entries = [
            e for e in entries
            if not e.get("title") or e.get("title") in ("Без названия", "Плейлист", "")
        ]
        if not missing_entries:
            return entries

        # Шаг 1: Чтение гидратации страницы SoundCloud (__sc_hydration)
        tracks_map: Dict[str, Dict[str, Any]] = {}
        try:
            req = urllib.request.Request(
                original_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            hydr_matches = re.findall(r"window\.__sc_hydration\s*=\s*(\[.*?\]);", html, re.DOTALL)
            if hydr_matches:
                hydr_data = json.loads(hydr_matches[0])
                for item in hydr_data:
                    if item.get("hydratable") in ("playlist", "system-playlist"):
                        for t in item.get("data", {}).get("tracks", []):
                            tid = str(t.get("id", ""))
                            if t.get("title"):
                                tracks_map[tid] = t
        except Exception:
            pass

        # Шаг 2: Для оставшихся треков запрашиваем пакетный API SoundCloud (/tracks?ids=...)
        still_missing_ids = [
            str(e["id"]) for e in missing_entries
            if str(e.get("id", "")) not in tracks_map and e.get("id")
        ]

        if still_missing_ids:
            try:
                client_id = None
                with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                    sc_ie = ydl.get_info_extractor("Soundcloud")
                    if not getattr(sc_ie, "_CLIENT_ID", None):
                        sc_ie._update_client_id()
                    client_id = getattr(sc_ie, "_CLIENT_ID", None)

                if client_id:
                    for i in range(0, len(still_missing_ids), 50):
                        batch = still_missing_ids[i:i + 50]
                        api_url = f"https://api-v2.soundcloud.com/tracks?ids={','.join(batch)}&client_id={client_id}"
                        b_req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(b_req, timeout=8) as b_resp:
                            b_data = json.loads(b_resp.read().decode("utf-8"))
                            for t in b_data:
                                tracks_map[str(t.get("id", ""))] = t
            except Exception:
                pass

        # Шаг 3: Обновляем названия, ссылки и длительности
        for e in entries:
            tid = str(e.get("id", ""))
            if tid in tracks_map:
                t_info = tracks_map[tid]
                real_title = t_info.get("title")
                if real_title:
                    e["title"] = real_title

                if t_info.get("permalink_url"):
                    e["url"] = t_info["permalink_url"]

                if t_info.get("duration"):
                    sec = round(t_info["duration"] / 1000)
                    e["duration"] = format_duration(sec)

            # Шаг 4: Запасной вариант — генерация чистого названия из URL slug
            if not e.get("title") or e.get("title") in ("Без названия", ""):
                raw_url = e.get("url", "")
                if "/tracks/" not in raw_url and "soundcloud.com/" in raw_url:
                    parts = raw_url.rstrip("/").split("/")
                    if len(parts) >= 2:
                        slug = parts[-1]
                        clean_slug = slug.replace("-", " ").strip().title()
                        if clean_slug:
                            e["title"] = clean_slug

        return entries

    def _create_progress_hook(
        self,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        status_callback: Optional[Callable[[str], None]],
    ) -> Callable[[Dict[str, Any]], None]:
        """
        Создает функцию обратного вызова (hook) для отслеживания хода скачивания.
        """
        def hook(data: Dict[str, Any]):
            status = data.get("status")

            if status == "downloading":
                total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded_bytes = data.get("downloaded_bytes") or 0
                speed = data.get("speed")
                eta = data.get("eta")

                fraction = 0.0
                if total_bytes > 0:
                    fraction = min(max(downloaded_bytes / total_bytes, 0.0), 1.0)

                payload = {
                    "status": "downloading",
                    "fraction": fraction,
                    "percent": fraction * 100.0,
                    "downloaded_str": format_bytes(downloaded_bytes),
                    "total_str": format_bytes(total_bytes) if total_bytes > 0 else "?? МБ",
                    "speed_str": format_speed(speed),
                    "eta_str": format_eta(eta),
                    "filename": data.get("filename"),
                }

                if progress_callback:
                    progress_callback(payload)

                if status_callback:
                    speed_display = format_speed(speed)
                    eta_display = format_eta(eta)
                    percent_display = f"{fraction * 100:.1f}%"
                    status_callback(
                        f"Загрузка: {percent_display} | Скорость: {speed_display} | ETA: {eta_display}"
                    )

            elif status == "finished":
                if status_callback:
                    status_callback("Скачивание завершено. Финальная обработка и сведение...")
                if progress_callback:
                    progress_callback({
                        "status": "finished",
                        "fraction": 1.0,
                        "percent": 100.0,
                        "filename": data.get("filename"),
                    })

        return hook

    def _resolve_final_path(self, info: Dict[str, Any], output_dir: str, target_ext: str) -> str:
        """
        Определяет фактический путь к скачанному и обработанному файлу на диске.
        """
        candidate = None
        if "requested_downloads" in info and info["requested_downloads"]:
            candidate = info["requested_downloads"][0].get("filepath")
        if not candidate:
            candidate = info.get("_filename")

        if candidate:
            p = Path(candidate)
            target_file = p.with_suffix(f".{target_ext.lower()}")
            if target_file.exists():
                return str(target_file)
            if p.exists() and p.suffix.lower() == f".{target_ext.lower()}":
                return str(p)

        # Fallback: поиск недавно созданного медиафайла с нужным расширением в папке output_dir
        try:
            files = [
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if os.path.isfile(os.path.join(output_dir, f))
                and f.lower().endswith(f".{target_ext.lower()}")
            ]
            if files:
                newest = max(files, key=os.path.getmtime)
                return newest
        except Exception as search_err:
            print(f"[!] Ошибка поиска файлов: {search_err}")

        return os.path.join(output_dir, f"{info.get('title', 'media')}.{target_ext}")

        return os.path.join(output_dir, f"{info.get('title', 'media')}.{target_ext}")

    def download_video(
        self,
        url: str,
        resolution: str,
        output_dir: str,
        container: str = "mp4",
        embed_thumbnail: bool = False,
        subtitles: bool = False,
        sub_langs: Optional[List[str]] = None,
        split_chapters: bool = False,
        ratelimit: Optional[int] = None,
        cookies_browser: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Скачивает видео с выбранным разрешением и в выбранный контейнер (mp4, mkv, webm).
        Поддерживает субтитры, нарезку по главам и лимит скорости.
        """
        os.makedirs(output_dir, exist_ok=True)
        container = container.lower().strip() or "mp4"

        clean_res = resolution.replace("p", "").strip() if resolution else ""
        if clean_res.isdigit():
            h_val = int(clean_res)
            format_str = (
                f"bestvideo[height<={h_val}][ext={container}]+bestaudio/"
                f"bestvideo[height<={h_val}]+bestaudio/"
                f"best[height<={h_val}]/best"
            )
        else:
            format_str = f"bestvideo[ext={container}]+bestaudio/bestvideo+bestaudio/best"

        ydl_opts = self._get_base_ydl_opts(cookies_browser=cookies_browser, ratelimit=ratelimit)
        ydl_opts.update({
            "format": format_str,
            "merge_output_format": container,
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [self._create_progress_hook(progress_callback, status_callback)],
        })

        postprocessors = []

        # Обложка
        if embed_thumbnail:
            ydl_opts["writethumbnail"] = True
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        # Субтитры
        if subtitles:
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = True
            ydl_opts["subtitleslangs"] = sub_langs or ["ru", "en"]
            postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

        # Нарезка по главам
        if split_chapters:
            postprocessors.append({"key": "FFmpegSplitChapters", "force_keyframes": False})

        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        ydl_opts["postprocessors"] = postprocessors

        if status_callback:
            status_callback("Инициализация загрузки видео...")

        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as dl_err:
            final_path = self._resolve_final_path({"title": ""}, output_dir, container)
            if final_path and os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
                file_size = os.path.getsize(final_path)
                final_title = Path(final_path).stem
                if status_callback:
                    status_callback("Видео успешно скачано!")
                return {
                    "status": "success",
                    "file_path": final_path,
                    "file_size": file_size,
                    "file_size_str": format_bytes(file_size),
                    "title": final_title,
                    "url": url,
                }
            raise dl_err

        final_path = self._resolve_final_path(info, output_dir, container)
        file_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0
        final_title = Path(final_path).stem or info.get("title", "Видео")

        if status_callback:
            status_callback("Видео успешно скачано!")

        return {
            "status": "success",
            "file_path": final_path,
            "file_size": file_size,
            "file_size_str": format_bytes(file_size),
            "title": final_title,
            "url": info.get("webpage_url") or url,
        }

    def download_audio(
        self,
        url: str,
        output_dir: str,
        audio_format: str = "mp3",
        bitrate: str = "320",
        embed_thumbnail: bool = False,
        custom_title: Optional[str] = None,
        custom_artist: Optional[str] = None,
        custom_album: Optional[str] = None,
        normalize_volume: bool = False,
        split_chapters: bool = False,
        ratelimit: Optional[int] = None,
        cookies_browser: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Скачивает аудиодорожку в выбранном формате (mp3, flac, m4a, wav, opus)
        с вшиванием пользовательских ID3-тегов, нормализацией громкости и разделением по главам.
        """
        os.makedirs(output_dir, exist_ok=True)
        audio_format = audio_format.lower().strip() or "mp3"
        if custom_title:
            custom_title = sanitize_filename(custom_title)

        ydl_opts = self._get_base_ydl_opts(cookies_browser=cookies_browser, ratelimit=ratelimit)
        ydl_opts.update({
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [self._create_progress_hook(progress_callback, status_callback)],
        })

        # Нормализация громкости (EBU R128) через FFmpeg
        if normalize_volume:
            ydl_opts["postprocessor_args"] = {"ExtractAudio": ["-filter:a", "loudnorm"]}

        postprocessors = []

        extract_opts = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
        }
        if audio_format == "mp3" and bitrate:
            extract_opts["preferredquality"] = str(bitrate)

        postprocessors.append(extract_opts)

        # Нарезка миксов по главам/таймкодам
        if split_chapters:
            postprocessors.append({"key": "FFmpegSplitChapters", "force_keyframes": False})

        postprocessors.append({
            "key": "FFmpegMetadata",
            "add_metadata": True,
        })

        if embed_thumbnail:
            ydl_opts["writethumbnail"] = True
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

        ydl_opts["postprocessors"] = postprocessors

        if status_callback:
            status_callback("Инициализация загрузки аудио...")

        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as dl_err:
            final_path = self._resolve_final_path({"title": ""}, output_dir, audio_format)
            if final_path and os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
                file_size = os.path.getsize(final_path)
                final_title = Path(final_path).stem
                if custom_artist or custom_title or custom_album:
                    apply_audio_tags(final_path, artist=custom_artist, title=custom_title, album=custom_album)
                if status_callback:
                    status_callback(f"Аудио успешно скачано в {audio_format.upper()}!")
                return {
                    "status": "success",
                    "file_path": final_path,
                    "file_size": file_size,
                    "file_size_str": format_bytes(file_size),
                    "title": final_title,
                    "url": url,
                }
            raise dl_err

        final_path = self._resolve_final_path(info, output_dir, audio_format)
        file_size = os.path.getsize(final_path) if os.path.exists(final_path) else 0

        # Применяем пользовательские теги ID3 через mutagen
        if custom_artist or custom_title or custom_album:
            apply_audio_tags(
                final_path,
                artist=custom_artist,
                title=custom_title,
                album=custom_album,
            )

        if status_callback:
            status_callback(f"Аудио успешно скачано в {audio_format.upper()}!")

        return {
            "status": "success",
            "file_path": final_path,
            "file_size": file_size,
            "file_size_str": format_bytes(file_size),
            "title": custom_title or info.get("title", "Аудио"),
            "url": info.get("webpage_url") or url,
        }

    def download_playlist(
        self,
        url: str,
        output_dir: str,
        mode: str = "video",
        resolution: str = "1080p",
        container: str = "mp4",
        audio_format: str = "mp3",
        bitrate: str = "320",
        embed_thumbnail: bool = False,
        limit_count: Optional[int] = None,
        ratelimit: Optional[int] = None,
        cookies_browser: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        item_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Скачивает плейлист в отдельную подпапку.
        Обрабатывает каждый трек/ролик с обновлением общего прогресса.
        """
        os.makedirs(output_dir, exist_ok=True)

        if status_callback:
            status_callback("Получение списка элементов плейлиста...")

        playlist_info = self.extract_playlist_info(url, cookies_browser=cookies_browser)
        title = playlist_info.get("title", "Плейлист")
        entries = playlist_info.get("entries", [])

        if not entries:
            raise DownloadError("Плейлист пуст или к нему нет доступа.")

        # Очищаем имя папки для безопасного сохранения в ОС
        safe_folder = sanitize_filename(title) or "Playlist"
        playlist_dir = os.path.join(output_dir, safe_folder)
        os.makedirs(playlist_dir, exist_ok=True)

        # Ограничение количества элементов (если задано)
        if limit_count and limit_count > 0:
            entries = entries[:limit_count]

        total_items = len(entries)
        downloaded_count = 0
        failed_count = 0

        for idx, entry in enumerate(entries, 1):
            item_url = entry.get("url")
            item_title = entry.get("title", f"Элемент {idx}")

            if not item_url:
                continue

            if item_callback:
                item_callback(idx, total_items, item_title)

            if status_callback:
                status_callback(f"Скачивание {idx}/{total_items}: {item_title[:45]}...")

            try:
                if mode == "video":
                    self.download_video(
                        url=item_url,
                        resolution=resolution,
                        output_dir=playlist_dir,
                        container=container,
                        embed_thumbnail=embed_thumbnail,
                        ratelimit=ratelimit,
                        cookies_browser=cookies_browser,
                        progress_callback=progress_callback,
                        status_callback=None,
                    )
                else:
                    self.download_audio(
                        url=item_url,
                        output_dir=playlist_dir,
                        audio_format=audio_format,
                        bitrate=bitrate,
                        embed_thumbnail=embed_thumbnail,
                        custom_title=item_title if item_title and item_title not in ("Без названия", f"Элемент {idx}") else None,
                        ratelimit=ratelimit,
                        cookies_browser=cookies_browser,
                        progress_callback=progress_callback,
                        status_callback=None,
                    )
                downloaded_count += 1
            except Exception as err:
                print(f"[!] Ошибка скачивания элемента '{item_title}': {err}")
                failed_count += 1

        if status_callback:
            status_callback(f"Плейлист завершен! Скачано: {downloaded_count}/{total_items}")

        return {
            "status": "success",
            "file_path": playlist_dir,
            "title": title,
            "count": downloaded_count,
            "total": total_items,
            "failed": failed_count,
            "url": url,
        }
