"""
Экраны загрузки музыки (music_views.py)
Содержит экраны для Spotify, SoundCloud, YouTube Music, других аудиохостингов и MusicHubView.
"""

from typing import Optional, List, Callable, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
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


class SpotifyTrackView(BaseDownloadView):
    def __init__(self, **kwargs):
        super().__init__(title="Spotify — Одиночный трек", icon_str="🎵", **kwargs)
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://open.spotify.com/track/... ссылка на трек Spotify")
        self._create_preview_card(is_square=True)

        # Редактор ID3 метаданных
        self.grp_meta = QGroupBox("ID3 Метаданные трека")
        meta_grid = QVBoxLayout(self.grp_meta)
        meta_grid.setSpacing(6)

        row_tags = QHBoxLayout()
        row_tags.setSpacing(8)
        self.txt_artist = QLineEdit()
        self.txt_artist.setPlaceholderText("Исполнитель")
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText("Название трека")
        self.txt_album = QLineEdit()
        self.txt_album.setPlaceholderText("Альбом")

        row_tags.addWidget(QLabel("Артист:"))
        row_tags.addWidget(self.txt_artist, 1)
        row_tags.addWidget(QLabel("Трек:"))
        row_tags.addWidget(self.txt_title, 1)
        row_tags.addWidget(QLabel("Альбом:"))
        row_tags.addWidget(self.txt_album, 1)
        meta_grid.addLayout(row_tags)
        self.content_layout.addWidget(self.grp_meta)

        # Опции аудио
        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["MP3", "FLAC", "AAC", "WAV", "OGG", "M4A"])
        self.cmb_format.setFixedWidth(100)

        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems(["320 kbps (HQ)", "256 kbps", "192 kbps", "128 kbps"])
        self.cmb_bitrate.setFixedWidth(140)

        self.chk_cover = QCheckBox("Вшить обложку")
        self.chk_cover.setChecked(True)
        self.chk_norm = QCheckBox("Нормализация громкости")

        row_params.addWidget(QLabel("Формат:"))
        row_params.addWidget(self.cmb_format)
        row_params.addWidget(QLabel("Битрейт:"))
        row_params.addWidget(self.cmb_bitrate)
        row_params.addWidget(self.chk_cover)
        row_params.addWidget(self.chk_norm)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать трек Spotify")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите корректную ссылку на трек Spotify!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ трека Spotify...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, False, None, is_spotify=True)
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
        self.status_lbl.setText("Трек готов к загрузке")

        tracks = info.get("tracks", [{}])
        t_data = tracks[0] if tracks else {}

        title = t_data.get("title", info.get("title", "Трек"))
        artist = t_data.get("artist", info.get("artist", "Исполнитель"))
        album = t_data.get("album", "")

        self.title_lbl.setText(title)
        self.author_lbl.setText(f"Исполнитель: {artist}")
        self.dur_badge.setText(f"⏱ {t_data.get('duration_str', '--:--')}")
        self.platform_badge.setText("Spotify Track")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        self.txt_title.setText(title)
        self.txt_artist.setText(artist)
        self.txt_album.setText(album)

        thumb_url = t_data.get("cover_url") or info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=True))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать трек:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_spotify": True,
            "is_playlist": False,
            "custom_artist": self.txt_artist.text().strip(),
            "custom_title": self.txt_title.text().strip(),
            "custom_album": self.txt_album.text().strip(),
            "embed_cover": self.chk_cover.isChecked(),
            "normalize_volume": self.chk_norm.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"Spotify {fmt.upper()}")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_spotify": True,
            "is_playlist": False,
            "custom_artist": self.txt_artist.text().strip(),
            "custom_title": self.txt_title.text().strip(),
            "custom_album": self.txt_album.text().strip(),
            "embed_cover": self.chk_cover.isChecked(),
            "normalize_volume": self.chk_norm.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
        }
        title = self.txt_title.text().strip() or self.title_lbl.text()
        self.queue_manager.add_task(media_type="spotify_track", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Трек Spotify добавлен в очередь загрузок!")


class SpotifyPlaylistView(BaseDownloadView):
    def __init__(self, **kwargs):
        super().__init__(title="Spotify — Альбом / Плейлист", icon_str="💿", **kwargs)
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://open.spotify.com/playlist/... или album/... ссылка")
        self._create_preview_card(is_square=True)

        # Интерактивный список треков коллекции
        self.grp_tracks = QGroupBox("Треки коллекции Spotify")
        self.grp_tracks.setVisible(False)
        tr_layout = QVBoxLayout(self.grp_tracks)
        self.list_tracks = QListWidget()
        self.list_tracks.setFixedHeight(140)
        tr_layout.addWidget(self.list_tracks)
        self.content_layout.addWidget(self.grp_tracks)

        # Опции
        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["MP3", "FLAC", "AAC", "WAV", "OGG"])
        self.cmb_format.setFixedWidth(100)

        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems(["320 kbps (HQ)", "256 kbps", "192 kbps", "128 kbps"])
        self.cmb_bitrate.setFixedWidth(140)

        self.cmb_limit = QComboBox()
        self.cmb_limit.addItems(["Все треки", "10", "25", "50", "100"])
        self.cmb_limit.setFixedWidth(120)

        self.chk_cover = QCheckBox("Вшить обложку")
        self.chk_cover.setChecked(True)
        self.chk_norm = QCheckBox("Нормализация")

        row_params.addWidget(QLabel("Формат:"))
        row_params.addWidget(self.cmb_format)
        row_params.addWidget(QLabel("Битрейт:"))
        row_params.addWidget(self.cmb_bitrate)
        row_params.addWidget(QLabel("Лимит:"))
        row_params.addWidget(self.cmb_limit)
        row_params.addWidget(self.chk_cover)
        row_params.addWidget(self.chk_norm)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать альбом Spotify")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку на альбом или плейлист Spotify!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ альбома Spotify...")
        self.percent_lbl.setText("Анализ...")
        self.progress_bar.setRange(0, 0)

        self.current_analyze_worker = AnalyzeWorker(self.downloader, self.spotify_downloader, url, True, None, is_spotify=True)
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
        self.status_lbl.setText("Коллекция готова к загрузке")

        title = info.get("title", "Коллекция Spotify")
        self.title_lbl.setText(title)
        self.author_lbl.setText(f"Автор / Владелец: {info.get('owner', info.get('artist', 'Spotify'))}")
        count = info.get("track_count", len(info.get("tracks", [])))
        self.dur_badge.setText(f"🎵 {count} треков")
        self.platform_badge.setText("Spotify Playlist")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        tracks = info.get("tracks", [])
        if tracks:
            self.grp_tracks.setVisible(True)
            self.list_tracks.clear()
            for idx, tr in enumerate(tracks[:60], 1):
                self.list_tracks.addItem(f"{idx}. {tr.get('artist', '')} — {tr.get('title', '')} [{tr.get('duration_str', '--:--')}]")
        else:
            self.grp_tracks.setVisible(False)

        thumb_url = info.get("cover_url") or info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=True))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать плейлист Spotify:\n{err}")

    def _get_limit_val(self) -> Optional[int]:
        txt = self.cmb_limit.currentText()
        if txt == "Все треки":
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

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_spotify": True,
            "is_playlist": True,
            "limit_count": self._get_limit_val(),
            "embed_cover": self.chk_cover.isChecked(),
            "normalize_volume": self.chk_norm.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"Spotify Альбом ({fmt.upper()})")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_spotify": True,
            "is_playlist": True,
            "limit_count": self._get_limit_val(),
            "embed_cover": self.chk_cover.isChecked(),
            "normalize_volume": self.chk_norm.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "Коллекция Spotify"
        self.queue_manager.add_task(media_type="spotify_collection", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Альбом Spotify добавлен в очередь загрузок!")


class SoundCloudView(BaseDownloadView):
    def __init__(self, is_playlist_mode: bool = False, **kwargs):
        title = "SoundCloud — Плейлист / Сет" if is_playlist_mode else "SoundCloud — Одиночный трек"
        super().__init__(title=title, icon_str="☁️", **kwargs)
        self.is_playlist_mode = is_playlist_mode
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://soundcloud.com/user/track или /sets/playlist ссылка")
        self._create_preview_card(is_square=True)

        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["MP3", "FLAC", "WAV", "AAC", "OGG"])
        self.cmb_format.setFixedWidth(100)

        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems(["320 kbps", "256 kbps", "192 kbps", "128 kbps"])
        self.cmb_bitrate.setFixedWidth(130)

        self.chk_cover = QCheckBox("Вшить обложку")
        self.chk_cover.setChecked(True)

        row_params.addWidget(QLabel("Формат:"))
        row_params.addWidget(self.cmb_format)
        row_params.addWidget(QLabel("Битрейт:"))
        row_params.addWidget(self.cmb_bitrate)
        row_params.addWidget(self.chk_cover)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать SoundCloud")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку на SoundCloud!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ SoundCloud...")
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
        self.status_lbl.setText("SoundCloud трек готов к загрузке")

        self.title_lbl.setText(info.get("title", "SoundCloud Трек"))
        self.author_lbl.setText(f"Исполнитель: {info.get('uploader', 'SoundCloud')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText("SoundCloud")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=True))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать SoundCloud:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"SoundCloud {fmt.upper()}")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "SoundCloud"
        self.queue_manager.add_task(media_type="audio", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "SoundCloud добавлен в очередь загрузок!")


class YTMusicView(BaseDownloadView):
    def __init__(self, is_playlist_mode: bool = False, **kwargs):
        title = "YouTube Music — Альбом / Плейлист" if is_playlist_mode else "YouTube Music — Одиночный трек"
        super().__init__(title=title, icon_str="🎧", **kwargs)
        self.is_playlist_mode = is_playlist_mode
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("https://music.youtube.com/watch?v=... или playlist?list=...")
        self._create_preview_card(is_square=True)

        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["MP3", "FLAC", "M4A", "WAV", "OGG"])
        self.cmb_format.setFixedWidth(100)

        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems(["320 kbps (HQ)", "256 kbps", "192 kbps", "128 kbps"])
        self.cmb_bitrate.setFixedWidth(140)

        self.chk_cover = QCheckBox("Вшить обложку")
        self.chk_cover.setChecked(True)

        row_params.addWidget(QLabel("Формат:"))
        row_params.addWidget(self.cmb_format)
        row_params.addWidget(QLabel("Битрейт:"))
        row_params.addWidget(self.cmb_bitrate)
        row_params.addWidget(self.chk_cover)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать YouTube Music")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку на YouTube Music!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ YouTube Music...")
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
        self.status_lbl.setText("YouTube Music готово к загрузке")

        self.title_lbl.setText(info.get("title", "Трек"))
        self.author_lbl.setText(f"Исполнитель: {info.get('uploader', 'YouTube Music')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText("YouTube Music")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=True))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать YouTube Music:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"YouTube Music {fmt.upper()}")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "YouTube Music"
        self.queue_manager.add_task(media_type="audio", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "YouTube Music добавлен в очередь загрузок!")


class OtherMusicView(BaseDownloadView):
    def __init__(self, is_playlist_mode: bool = False, **kwargs):
        title = "Другая музыка — Плейлист" if is_playlist_mode else "Другая музыка — Одиночный трек"
        super().__init__(title=title, icon_str="📻", **kwargs)
        self.is_playlist_mode = is_playlist_mode
        self._init_ui()

    def _init_ui(self):
        self._create_url_row("Ссылка на Bandcamp, прямую аудиоссылку mp3 или веб-радио")
        self._create_preview_card(is_square=True)

        row_params = QHBoxLayout()
        row_params.setSpacing(12)

        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["MP3", "FLAC", "AAC", "WAV", "OGG"])
        self.cmb_format.setFixedWidth(100)

        self.cmb_bitrate = QComboBox()
        self.cmb_bitrate.addItems(["320 kbps (HQ)", "256 kbps", "192 kbps", "128 kbps"])
        self.cmb_bitrate.setFixedWidth(140)

        self.chk_cover = QCheckBox("Вшить обложку")
        self.chk_cover.setChecked(True)

        row_params.addWidget(QLabel("Формат:"))
        row_params.addWidget(self.cmb_format)
        row_params.addWidget(QLabel("Битрейт:"))
        row_params.addWidget(self.cmb_bitrate)
        row_params.addWidget(self.chk_cover)
        row_params.addStretch()
        self.content_layout.addLayout(row_params)

        self._create_folder_row()
        self._create_progress_card()
        self._create_actions_row("Скачать аудио")
        self.content_layout.addStretch()

    def start_analyze(self):
        url = self.url_input.text().strip()
        if not url or not is_valid_url(url):
            QMessageBox.warning(self, "Ошибка", "Укажите корректную ссылку!")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.status_lbl.setText("Анализ аудио...")
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
        self.status_lbl.setText("Аудио готово к загрузке")

        self.title_lbl.setText(info.get("title", "Аудиозапись"))
        self.author_lbl.setText(f"Источник / Артист: {info.get('uploader', 'Неизвестно')}")
        self.dur_badge.setText(f"⏱ {info.get('duration_str', '--:--')}")
        self.platform_badge.setText(f"{info.get('extractor', 'Аудио')}")
        self.btn_open_browser.setEnabled(True)
        self._current_source_url = self.url_input.text()
        self._current_media_info = info

        thumb_url = info.get("thumbnail_url")
        if thumb_url:
            self.thumb_worker = ThumbnailWorker(thumb_url)
            self.thumb_worker.sig_loaded.connect(lambda p: self._on_thumb_loaded(p, is_square=True))
            self.thumb_worker.start()

    def _on_analyze_error(self, err: str):
        self.btn_analyze.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        self.status_lbl.setText(f"Ошибка: {err[:40]}...")
        QMessageBox.critical(self, "Ошибка анализа", f"Не удалось проанализировать аудио:\n{err}")

    def start_download(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для скачивания!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]

        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        self._start_download_worker(opts, media_title=self.title_lbl.text(), format_str=f"Аудио {fmt.upper()}")

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите ссылку для очереди!")
            return

        fmt = self.cmb_format.currentText().split()[0].lower()
        bitrate = self.cmb_bitrate.currentText().split()[0]
        opts = {
            "url": url,
            "save_dir": self.folder_input.text().strip() or get_default_download_dir(),
            "mode": "audio",
            "audio_format": fmt,
            "bitrate": bitrate,
            "is_playlist": self.is_playlist_mode,
            "embed_cover": self.chk_cover.isChecked(),
            "ratelimit": self.get_speed_limit_cb(),
            "cookies_browser": self.get_cookies_cb(),
        }
        title = self.title_lbl.text() if self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "Аудио"
        self.queue_manager.add_task(media_type="audio", title=title, url=url, options=opts)
        self.on_queue_added_cb()
        QMessageBox.information(self, "Очередь", "Аудио добавлено в очередь загрузок!")


class MusicHubView(QWidget):
    """
    Управляет независимыми экранами музыкальных сервисов:
    - Spotify Одиночный трек
    - Spotify Альбом / Плейлист
    - SoundCloud Одиночный трек
    - SoundCloud Плейлист / Сет
    - YouTube Music Одиночный трек
    - YouTube Music Альбом / Плейлист
    - Другие аудио сервисы
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

        # Верхняя панель
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(0, 0, 0, 4)
        ctrl_bar.setSpacing(12)
        self.seg_platform = SegmentedButton([
            ("Spotify", "🎧 Spotify"),
            ("SoundCloud", "☁️ SoundCloud"),
            ("YouTube Music", "▶️ YouTube Music"),
            ("Другие сервисы", "🌐 Другие сервисы"),
        ], active="Spotify")
        self.seg_platform.selectionChanged.connect(self._on_platform_changed)

        self.seg_mode = SegmentedButton([
            ("Одиночный трек", "🎵 Одиночный трек"),
            ("Альбом / Плейлист", "💿 Альбом / Плейлист"),
        ], active="Одиночный трек")
        self.seg_mode.selectionChanged.connect(self._on_mode_changed)

        ctrl_bar.addWidget(self.seg_platform)
        ctrl_bar.addStretch()
        ctrl_bar.addWidget(self.seg_mode)
        layout.addLayout(ctrl_bar)

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

        self.view_sp_track = SpotifyTrackView(**kwargs)
        self.view_sp_playlist = SpotifyPlaylistView(**kwargs)
        self.view_sc_track = SoundCloudView(is_playlist_mode=False, **kwargs)
        self.view_sc_playlist = SoundCloudView(is_playlist_mode=True, **kwargs)
        self.view_ytm_track = YTMusicView(is_playlist_mode=False, **kwargs)
        self.view_ytm_playlist = YTMusicView(is_playlist_mode=True, **kwargs)
        self.view_other_track = OtherMusicView(is_playlist_mode=False, **kwargs)
        self.view_other_playlist = OtherMusicView(is_playlist_mode=True, **kwargs)

        self.stack.addWidget(self.view_sp_track)         # 0
        self.stack.addWidget(self.view_sp_playlist)      # 1
        self.stack.addWidget(self.view_sc_track)         # 2
        self.stack.addWidget(self.view_sc_playlist)      # 3
        self.stack.addWidget(self.view_ytm_track)        # 4
        self.stack.addWidget(self.view_ytm_playlist)     # 5
        self.stack.addWidget(self.view_other_track)      # 6
        self.stack.addWidget(self.view_other_playlist)   # 7

        layout.addWidget(self.stack, 1)

    def get_all_views(self) -> List[BaseDownloadView]:
        return [
            self.view_sp_track, self.view_sp_playlist, self.view_sc_track,
            self.view_sc_playlist, self.view_ytm_track, self.view_ytm_playlist,
            self.view_other_track, self.view_other_playlist
        ]

    def _on_platform_changed(self, platform: str):
        self._update_current_widget()

    def _on_mode_changed(self, mode: str):
        self._update_current_widget()

    def _update_current_widget(self):
        plat = self.seg_platform.currentText()
        is_pl = self.seg_mode.currentText() == "Альбом / Плейлист"

        if plat == "Spotify":
            self.stack.setCurrentWidget(self.view_sp_playlist if is_pl else self.view_sp_track)
        elif plat == "SoundCloud":
            self.stack.setCurrentWidget(self.view_sc_playlist if is_pl else self.view_sc_track)
        elif plat == "YouTube Music":
            self.stack.setCurrentWidget(self.view_ytm_playlist if is_pl else self.view_ytm_track)
        else:
            self.stack.setCurrentWidget(self.view_other_playlist if is_pl else self.view_other_track)

    def switch_to(self, platform: str, is_playlist: bool = False):
        self.seg_platform.select(platform)
        self.seg_mode.select("Альбом / Плейлист" if is_playlist else "Одиночный трек")
        self._update_current_widget()
