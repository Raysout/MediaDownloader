"""
Экраны загрузки видео (video_views.py)
Содержит экраны для YouTube, TikTok, других видеохостингов и VideoHubView.
"""

from typing import Optional, List, Callable, Dict, Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QListWidget,
    QGroupBox, QStackedWidget, QMessageBox
)

from media_downloader.core import (
    MediaDownloader,
    SpotifyDownloader,
    DownloadQueueManager,
)
from media_downloader.ui.base_view import BaseDownloadView
from media_downloader.ui.widgets import SegmentedButton
from media_downloader.ui.workers import AnalyzeWorker, ThumbnailWorker
from media_downloader.utils import is_valid_url, get_default_download_dir


class YouTubeSingleVideoView(BaseDownloadView):
    def __init__(self, **kwargs):
        super().__init__(title="YouTube — Одиночное видео / Shorts", icon_str="🎬", **kwargs)
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://www.youtube.com/watch?v=... или ссылка на Shorts")
        self._create_preview_card(is_square=False)

        # Опции качества видео
        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_res = QComboBox()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.cmb_res.setFixedWidth(160)

        self.cmb_container = QComboBox()
        self.cmb_container.addItems(["MP4", "MKV", "WEBM", "AVI", "MOV"])
        self.cmb_container.setFixedWidth(110)

        self.chk_subs = QCheckBox("Вшить русские субтитры")

        row_params.addWidget(QLabel("Разрешение:"))
        row_params.addWidget(self.cmb_res)
        row_params.addWidget(QLabel("Контейнер:"))
        row_params.addWidget(self.cmb_container)
        row_params.addWidget(self.chk_subs)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать видео")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите корректную ссылку на ролик YouTube!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("Анализ разрешений...")
        self.cmb_res.setEnabled(False)
        self.status_lbl.setText("Анализ ролика через yt-dlp...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        cb = self.get_cookies_cb()
        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, False, cb, is_spotify=False)
        self.current_analyze_worker.sig_success.connect(self._on_analyze_success)
        self.current_analyze_worker.sig_error.connect(self._on_analyze_error)
        self.current_analyze_worker.start()

    def _on_analyze_success(self, info: dict):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0.0%")
        self.status_lbl.setText("Видео готово к загрузке")

        self.title_lbl.setText(info.get("title", "Без названия"))
        self.author_lbl.setText(f"Канал: {info.get('uploader', 'Неизвестно')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText(f"YouTube ({info.get('resolution', 'HD')})")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = info.get("url") or self.url_input.text()
        self._current_media_info = info

        resolutions = info.get("resolutions", [])
        self.cmb_res.clear()
        if resolutions:
            self.cmb_res.addItems(resolutions)
        else:
            self.cmb_res.addItems(["best (Максимум)", "1080p", "720p", "480p", "360p"])
        self.cmb_res.setEnabled(True)

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=False))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать ролик:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": False,
            "subtitles": self.chk_subs.isChecked(),
            "sub_langs": ["ru"],
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"YouTube {res} ({container.upper()})")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": False,
            "subtitles": self.chk_subs.isChecked(),
            "sub_langs": ["ru"],
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "YouTube Видео"
        self.queue_manager.add_task(media_type="video", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Видеоролик успешно добавлен в очередь загрузок!")


class YouTubePlaylistView(BaseDownloadView):
    def __init__(self, **kwargs):
        super().__init__(title="YouTube — Плейлист / Канал", icon_str="📑", **kwargs)
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://www.youtube.com/playlist?list=... или ссылка на канал")
        self._create_preview_card(is_square=False)

        # Список роликов плейлиста
        self.grp_playlist = QGroupBox("Содержимое плейлиста")
        self.grp_playlist.setVisible(False)
        pl_layout = QVBoxLayout(self.grp_playlist)
        self.list_entries = QListWidget()
        self.list_entries.setFixedHeight(140)
        pl_layout.addWidget(self.list_entries)
        self.content_layout.addWidget(self.grp_playlist)

        # Опции качества и лимита
        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_res = QComboBox()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.cmb_res.setFixedWidth(160)

        self.cmb_container = QComboBox()
        self.cmb_container.addItems(["MP4", "MKV", "WEBM"])
        self.cmb_container.setFixedWidth(110)

        self.cmb_limit = QComboBox()
        self.cmb_limit.addItems(["Все ролики", "5", "10", "25", "50", "100"])
        self.cmb_limit.setFixedWidth(130)

        self.chk_subs = QCheckBox("Субтитры")

        row_params.addWidget(QLabel("Разрешение:"))
        row_params.addWidget(self.cmb_res)
        row_params.addWidget(QLabel("Контейнер:"))
        row_params.addWidget(self.cmb_container)
        row_params.addWidget(QLabel("Количество:"))
        row_params.addWidget(self.cmb_limit)
        row_params.addWidget(self.chk_subs)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать плейлист")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите корректную ссылку на плейлист или канал!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("Анализ разрешений...")
        self.cmb_res.setEnabled(False)
        self.status_lbl.setText("Анализ плейлиста через yt-dlp...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        cb = self.get_cookies_cb()
        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, True, cb, is_spotify=False)
        self.current_analyze_worker.sig_success.connect(self._on_analyze_success)
        self.current_analyze_worker.sig_error.connect(self._on_analyze_error)
        self.current_analyze_worker.start()

    def _on_analyze_success(self, info: dict):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0.0%")
        self.status_lbl.setText("Плейлист готов к загрузке")

        title = info.get("title", "Плейлист YouTube")
        self.title_lbl.setText(title)
        self.author_lbl.setText(f"Канал / Автор: {info.get('uploader', 'Неизвестно')}")
        count = info.get("playlist_count", len(info.get("entries", [])))
        self.dur_badge.setText(f"📹 {count} видео")
        self.platform_badge.setText("YouTube Плейлист")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        entries = info.get("entries", [])
        if entries:
            self.grp_playlist.setVisible(True)
            self.list_entries.clear()
            for idx, item in enumerate(entries[:50], 1):
                self.list_entries.addItem(f"{idx}. {item.get('title', 'Без названия')} [{item.get('duration', '--:--')}]")
        else:
            self.grp_playlist.setVisible(False)

        resolutions = info.get("resolutions", [])
        self.cmb_res.clear()
        if resolutions:
            self.cmb_res.addItems(resolutions)
        else:
            self.cmb_res.addItems(["1080p (Full HD)", "720p (HD)", "480p", "best (Максимум)"])
        self.cmb_res.setEnabled(True)

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=False))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать плейлист:\n{err}")

    def _get_limit_val(self) -> Optional[int]:
        txt = self.cmb_limit.currentText()
        if txt == "Все ролики":
            return None
        try:
            return int(txt)
        except Exception:
            return None

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": True,
            "limit_count": self._get_limit_val(),
            "subtitles": self.chk_subs.isChecked(),
            "sub_langs": ["ru"],
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"YouTube Плейлист ({container.upper()})")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": True,
            "limit_count": self._get_limit_val(),
            "subtitles": self.chk_subs.isChecked(),
            "sub_langs": ["ru"],
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "YouTube Плейлист"
        self.queue_manager.add_task(media_type="playlist", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Плейлист успешно добавлен в очередь загрузок!")


class TikTokVideoView(BaseDownloadView):
    def __init__(self, **kwargs):
        super().__init__(title="TikTok — Клипы и Музыка", icon_str="📱", **kwargs)
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://www.tiktok.com/@user/video/... или короткая ссылка vt.tiktok.com")
        self._create_preview_card(is_square=False)

        # Опции TikTok
        row_params = QHBoxLayout()
        row_params.setSpacing(16)
        self.chk_audio_only = QCheckBox("Скачать только оригинальный звук (MP3)")
        self.chk_no_watermark = QCheckBox("Удалить водяной знак (по возможности)")
        self.chk_no_watermark.setChecked(True)

        row_params.addWidget(self.chk_no_watermark)
        row_params.addWidget(self.chk_audio_only)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать из TikTok")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку на ролик TikTok!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ клипа TikTok...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        cb = self.get_cookies_cb()
        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, False, cb, is_spotify=False)
        self.current_analyze_worker.sig_success.connect(self._on_analyze_success)
        self.current_analyze_worker.sig_error.connect(self._on_analyze_error)
        self.current_analyze_worker.start()

    def _on_analyze_success(self, info: dict):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0.0%")
        self.status_lbl.setText("Клип TikTok готов к загрузке")

        self.title_lbl.setText(info.get("title", "TikTok Клип"))
        self.author_lbl.setText(f"Автор: {info.get('uploader', 'TikTok Автор')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText("TikTok")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=False))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать ролик TikTok:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        is_audio = self.chk_audio_only.isChecked()
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio" if is_audio else "video",
            "tiktok_audio": is_audio,
            "audio_format": "mp3",
            "resolution": "best",
            "container": "mp4",
            "is_playlist": False,
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        fmt_str = "TikTok MP3" if is_audio else "TikTok MP4"
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=fmt_str)

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        is_audio = self.chk_audio_only.isChecked()
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio" if is_audio else "video",
            "tiktok_audio": is_audio,
            "audio_format": "mp3",
            "resolution": "best",
            "container": "mp4",
            "is_playlist": False,
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "TikTok Клип"
        self.queue_manager.add_task(media_type="tiktok", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "TikTok успешно добавлен в очередь загрузок!")


class OtherVideoView(BaseDownloadView):
    def __init__(self, is_playlist_mode: bool = False, **kwargs):
        title = "Другие видео — Плейлист" if is_playlist_mode else "Другие видео — Одиночный ролик"
        super().__init__(title=title, icon_str="🌐", **kwargs)
        self.is_playlist_mode = is_playlist_mode
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("Ссылка на ролик VK, RuTube, Instagram Reels, Twitch, Vimeo и др.")
        self._create_preview_card(is_square=False)

        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_res = QComboBox()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.cmb_res.setFixedWidth(160)

        self.cmb_container = QComboBox()
        self.cmb_container.addItems(["MP4", "MKV", "WEBM"])
        self.cmb_container.setFixedWidth(110)

        row_params.addWidget(QLabel("Разрешение:"))
        row_params.addWidget(self.cmb_res)
        row_params.addWidget(QLabel("Контейнер:"))
        row_params.addWidget(self.cmb_container)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать видео")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите корректную ссылку!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("Анализ разрешений...")
        self.cmb_res.setEnabled(False)
        self.status_lbl.setText("Анализ видео...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        cb = self.get_cookies_cb()
        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, self.is_playlist_mode, cb, is_spotify=False)
        self.current_analyze_worker.sig_success.connect(self._on_analyze_success)
        self.current_analyze_worker.sig_error.connect(self._on_analyze_error)
        self.current_analyze_worker.start()

    def _on_analyze_success(self, info: dict):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0.0%")
        self.status_lbl.setText("Медиа готово к загрузке")

        self.title_lbl.setText(info.get("title", "Медиафайл"))
        self.author_lbl.setText(f"Источник / Автор: {info.get('uploader', 'Неизвестно')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText(f"{info.get('extractor', 'Медиа')}")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        resolutions = info.get("resolutions", [])
        self.cmb_res.clear()
        if resolutions:
            self.cmb_res.addItems(resolutions)
        else:
            self.cmb_res.addItems(["1080p (Full HD)", "720p (HD)", "480p", "best (Максимум)"])
        self.cmb_res.setEnabled(True)

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=False))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.cmb_res.clear()
        self.cmb_res.addItem("None")
        self.cmb_res.setEnabled(False)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать ссылку:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": self.is_playlist_mode,
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"Видео {res} ({container.upper()})")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        res = self.cmb_res.currentText().split()[0]
        container = self.cmb_container.currentText().lower()
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "video",
            "resolution": res,
            "container": container,
            "is_playlist": self.is_playlist_mode,
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "Видео"
        self.queue_manager.add_task(media_type="video", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Видео добавлено в очередь загрузок!")


class VideoHubView(QWidget):
    """
    Управляет независимыми экранами видео-сервисов:
    - YouTube Одиночное видео
    - YouTube Плейлист / Канал
    - TikTok Клипы и Звук
    - Другие сервисы — Одиночное видео
    - Другие сервисы — Плейлист
    """
    def __init__(
        self,
        downloader: MediaDownloader,
        spotify_downloader: SpotifyDownloader,
        queue_manager: DownloadQueueManager,
        get_cookies_cb: Callable,
        get_speed_limit_cb: Callable,
        on_queue_added_cb: Callable,
        on_history_added_cb: Callable,
        on_detach_requested_cb: Callable,
        on_download_started_cb: Optional[Callable] = None,
        on_go_to_downloads_cb: Optional[Callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Верхняя панель переключения сервисов и режимов
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(0, 0, 0, 4)
        ctrl_bar.setSpacing(12)
        self.seg_platform = SegmentedButton([
            ("YouTube", "▶️ YouTube"),
            ("TikTok", "🎵 TikTok"),
            ("Другие сервисы", "🌐 Другие сервисы"),
        ], active="YouTube")
        self.seg_platform.selectionChanged.connect(self._on_platform_changed)

        self.seg_mode = SegmentedButton([
            ("Одиночное видео", "🎬 Одиночное видео"),
            ("Плейлист / Канал", "📑 Плейлист / Канал"),
        ], active="Одиночное видео")
        self.seg_mode.selectionChanged.connect(self._on_mode_changed)

        ctrl_bar.addWidget(self.seg_platform)
        ctrl_bar.addStretch()
        ctrl_bar.addWidget(self.seg_mode)
        layout.addLayout(ctrl_bar)

        # Стек независимых окон для каждого сервиса и режима
        self.stack = QStackedWidget()

        kwargs = {
            "downloader": downloader,
            "spotify_downloader": spotify_downloader,
            "queue_manager": queue_manager,
            "get_cookies_cb": get_cookies_cb,
            "get_speed_limit_cb": get_speed_limit_cb,
            "on_queue_added_cb": on_queue_added_cb,
            "on_history_added_cb": on_history_added_cb,
            "on_detach_requested_cb": on_detach_requested_cb,
            "on_download_started_cb": on_download_started_cb,
            "on_go_to_downloads_cb": on_go_to_downloads_cb,
        }

        self.view_yt_single = YouTubeSingleVideoView(**kwargs)
        self.view_yt_playlist = YouTubePlaylistView(**kwargs)
        self.view_tiktok = TikTokVideoView(**kwargs)
        self.view_other_single = OtherVideoView(is_playlist_mode=False, **kwargs)
        self.view_other_playlist = OtherVideoView(is_playlist_mode=True, **kwargs)

        self.stack.addWidget(self.view_yt_single)        # 0
        self.stack.addWidget(self.view_yt_playlist)      # 1
        self.stack.addWidget(self.view_tiktok)           # 2
        self.stack.addWidget(self.view_other_single)     # 3
        self.stack.addWidget(self.view_other_playlist)   # 4

        layout.addWidget(self.stack, 1)

    def get_all_views(self) -> List[BaseDownloadView]:
        return [
            self.view_yt_single, self.view_yt_playlist, self.view_tiktok,
            self.view_other_single, self.view_other_playlist
        ]

    def _on_platform_changed(self, platform: str):
        if platform == "TikTok":
            self.seg_mode.setVisible(False)
            self.stack.setCurrentWidget(self.view_tiktok)
        else:
            self.seg_mode.setVisible(True)
            self._update_current_widget()

    def _on_mode_changed(self, mode: str):
        self._update_current_widget()

    def _update_current_widget(self):
        plat = self.seg_platform.currentText()
        is_pl = self.seg_mode.currentText() == "Плейлист / Канал"

        if plat == "YouTube":
            self.stack.setCurrentWidget(self.view_yt_playlist if is_pl else self.view_yt_single)
        elif plat == "TikTok":
            self.stack.setCurrentWidget(self.view_tiktok)
        else:
            self.stack.setCurrentWidget(self.view_other_playlist if is_pl else self.view_other_single)

    def switch_to(self, platform: str, is_playlist: bool = False):
        self.seg_platform.select(platform)
        if platform != "TikTok":
            self.seg_mode.select("Плейлист / Канал" if is_playlist else "Одиночное видео")
        self._update_current_widget()
