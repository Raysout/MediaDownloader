"""
Модуль фоновых потоков (workers.py)
Содержит QThread воркеры для анализа, скачивания и подгрузки превью.
"""

import time
import urllib.request
from typing import Dict, Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from media_downloader.core import add_history_entry
from media_downloader.utils import get_default_download_dir


class ThumbnailWorker(QThread):
    sig_loaded = pyqtSignal(QPixmap)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        if not self.url or not self.url.startswith("http"):
            return
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                data = response.read()
                image = QImage()
                if image.loadFromData(data):
                    pixmap = QPixmap.fromImage(image)
                    self.sig_loaded.emit(pixmap)
        except Exception:
            pass


class AnalyzeWorker(QThread):
    sig_started = pyqtSignal()
    sig_success = pyqtSignal(dict)
    sig_error = pyqtSignal(str)

    def __init__(self, downloader, spotify_downloader, url: str, is_playlist: bool, cookies_browser: Optional[str], is_spotify: bool = False):
        super().__init__()
        self.downloader = downloader
        self.spotify_downloader = spotify_downloader
        self.url = url
        self.is_playlist = is_playlist
        self.cookies_browser = cookies_browser
        self.is_spotify = is_spotify

    def run(self):
        self.sig_started.emit()
        try:
            if self.is_spotify:
                info = self.spotify_downloader.extract_info(self.url)
            elif self.is_playlist:
                info = self.downloader.extract_playlist_info(self.url, cookies_browser=self.cookies_browser)
            else:
                info = self.downloader.extract_info(self.url, cookies_browser=self.cookies_browser)

            if not info or info.get("error"):
                err = info.get("error") if info else "Не удалось получить метаданные"
                self.sig_error.emit(err)
            else:
                self.sig_success.emit(info)
        except Exception as exc:
            self.sig_error.emit(str(exc))


class DownloadWorker(QThread):
    sig_progress = pyqtSignal(dict)
    sig_status = pyqtSignal(str)
    sig_finished = pyqtSignal(dict)
    sig_error = pyqtSignal(str)

    def __init__(self, downloader, spotify_downloader, options: Dict[str, Any]):
        super().__init__()
        self.downloader = downloader
        self.spotify_downloader = spotify_downloader
        self.options = options
        self._last_time = 0.0

    def _progress_hook(self, p_dict: Dict[str, Any]):
        now = time.time()
        is_finished = p_dict.get("status") == "finished" or p_dict.get("fraction", 0.0) >= 1.0
        if not is_finished and (now - self._last_time) < 0.05:
            return
        self._last_time = now
        self.sig_progress.emit(p_dict)

    def _status_hook(self, text: str):
        if not text.startswith("Загрузка:"):
            self.sig_status.emit(text)

    def run(self):
        opts = self.options
        url = opts["url"]
        save_dir = opts.get("save_dir") or get_default_download_dir()
        is_spotify = opts.get("is_spotify", False)
        is_audio = opts.get("mode") == "audio"
        is_playlist = opts.get("is_playlist", False)

        try:
            if is_spotify:
                if is_playlist:
                    col_info = self.spotify_downloader.extract_info(url)
                    res = self.spotify_downloader.download_collection(
                        collection_info=col_info,
                        output_dir=save_dir,
                        audio_format=opts.get("audio_format", "mp3"),
                        bitrate=opts.get("bitrate", "320"),
                        embed_thumbnail=opts.get("embed_cover", True),
                        normalize_volume=opts.get("normalize_volume", False),
                        limit_count=opts.get("limit_count"),
                        ratelimit=opts.get("ratelimit"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                    )
                    add_history_entry(
                        title=res.get("title", "Коллекция Spotify"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type="Плейлист Spotify",
                        file_size_str=f"{res.get('count', 0)} треков",
                    )
                else:
                    s_info = self.spotify_downloader.extract_info(url)
                    tracks = s_info.get("tracks", [{}])
                    t_data = tracks[0] if tracks else {}
                    if opts.get("custom_artist"):
                        t_data["artist"] = opts["custom_artist"]
                    if opts.get("custom_title"):
                        t_data["title"] = opts["custom_title"]
                    if opts.get("custom_album"):
                        t_data["album"] = opts["custom_album"]

                    res = self.spotify_downloader.download_track(
                        track_data=t_data,
                        output_dir=save_dir,
                        audio_format=opts.get("audio_format", "mp3"),
                        bitrate=opts.get("bitrate", "320"),
                        embed_thumbnail=opts.get("embed_cover", True),
                        normalize_volume=opts.get("normalize_volume", False),
                        ratelimit=opts.get("ratelimit"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                    )
                    add_history_entry(
                        title=res.get("title", "Трек Spotify"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type=f"Spotify {opts.get('audio_format', 'mp3').upper()}",
                        file_size_str=res.get("file_size_str", "OK"),
                    )

            elif is_audio:
                if is_playlist:
                    res = self.downloader.download_playlist(
                        playlist_url=url,
                        output_dir=save_dir,
                        mode="audio",
                        audio_format=opts.get("audio_format", "mp3"),
                        bitrate=opts.get("bitrate", "320"),
                        limit=opts.get("limit_count"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                        cookies_browser=opts.get("cookies_browser"),
                        ratelimit=opts.get("ratelimit"),
                    )
                    add_history_entry(
                        title=res.get("title", "Аудио-плейлист"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type=f"Аудио {opts.get('audio_format', 'mp3').upper()}",
                        file_size_str=f"{res.get('count', 0)} файлов",
                    )
                else:
                    res = self.downloader.download_audio(
                        url=url,
                        output_dir=save_dir,
                        audio_format=opts.get("audio_format", "mp3"),
                        bitrate=opts.get("bitrate", "320"),
                        embed_thumbnail=opts.get("embed_cover", True),
                        ratelimit=opts.get("ratelimit"),
                        cookies_browser=opts.get("cookies_browser"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                    )
                    add_history_entry(
                        title=res.get("title", "Аудиозапись"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type=f"Аудио {opts.get('audio_format', 'mp3').upper()}",
                        file_size_str=res.get("file_size_str", "OK"),
                    )

            else:
                # Видео
                if is_playlist:
                    res = self.downloader.download_playlist(
                        playlist_url=url,
                        output_dir=save_dir,
                        mode="video",
                        resolution=opts.get("resolution", "best"),
                        container=opts.get("container", "mp4"),
                        subtitles=opts.get("subtitles", False),
                        sub_langs=opts.get("sub_langs", ["ru"]),
                        limit=opts.get("limit_count"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                        cookies_browser=opts.get("cookies_browser"),
                        ratelimit=opts.get("ratelimit"),
                    )
                    add_history_entry(
                        title=res.get("title", "Видео-плейлист"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type=f"Плейлист {opts.get('resolution', 'HD')}",
                        file_size_str=f"{res.get('count', 0)} видео",
                    )
                elif opts.get("tiktok_audio", False):
                    res = self.downloader.download_audio(
                        url=url,
                        output_dir=save_dir,
                        audio_format="mp3",
                        bitrate="320",
                        embed_thumbnail=True,
                        ratelimit=opts.get("ratelimit"),
                        cookies_browser=opts.get("cookies_browser"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                    )
                    add_history_entry(
                        title=res.get("title", "TikTok Звук"),
                        url=url,
                        file_path=res.get("file_path", ""),
                        format_type="TikTok MP3",
                        file_size_str=res.get("file_size_str", "OK"),
                    )
                else:
                    res = self.downloader.download_video(
                        url=url,
                        output_dir=save_dir,
                        resolution=opts.get("resolution", "best"),
                        container=opts.get("container", "mp4"),
                        subtitles=opts.get("subtitles", False),
                        sub_langs=opts.get("sub_langs", ["ru"]),
                        ratelimit=opts.get("ratelimit"),
                        cookies_browser=opts.get("cookies_browser"),
                        progress_callback=self._progress_hook,
                        status_callback=self._status_hook,
                    )
                    if isinstance(res, dict) and res.get("status") != "error":
                        try:
                            add_history_entry(
                                title=res.get("title", "Видеоролик"),
                                url=url,
                                file_path=res.get("file_path", ""),
                                format_type=f"Видео {opts.get('resolution', 'HD')} ({opts.get('container', 'mp4').upper()})",
                                file_size_str=res.get("file_size_str", "OK"),
                            )
                        except Exception as h_err:
                            print(f"[!] Ошибка сохранения в историю: {h_err}")

            if not isinstance(res, dict) or res.get("status") == "error":
                err_text = res.get("error", "Произошла ошибка при скачивании") if isinstance(res, dict) else "Неизвестная ошибка скачивания"
                self.sig_error.emit(err_text)
            else:
                self.sig_finished.emit(res)

        except BaseException as exc:
            self.sig_error.emit(str(exc))
