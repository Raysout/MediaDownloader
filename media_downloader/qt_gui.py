"""
Модуль графического интерфейса на PyQt6 (qt_gui.py)
Стилизован в современном Material 3 дизайне:
- Полноценный сайдбар с фирменным брендом, пилюлевидными кнопками навигации и бейджами-счетчиками
- Для каждого сервиса (YouTube, TikTok, Spotify, SoundCloud, YouTube Music, Другие сервисы)
  и для каждого режима (Одиночное видео / трек, Плейлист / Альбом) создано ОТДЕЛЬНОЕ ОКНО (отдельный экран/виджет)
  со своим независимым состоянием ввода, превью, качеством, папкой сохранения и дашбордом прогресса
- Поддержка открепления любого сервиса в независимое плавающее окно ("↗ Открыть в отдельном окне")
- 100% нативная потокобезопасная работа через QThread и pyqtSignal (60 FPS без задержек)
- Гарантированное чистое закрытие по Alt+F4 и крестику окна
"""

import os
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QUrl,
    qInstallMessageHandler, QtMsgType, QTranslator, QLibraryInfo, QLocale
)
from PyQt6.QtGui import (
    QPixmap, QImage, QFont, QDesktopServices,
    QPainter, QPainterPath
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QProgressBar,
    QStackedWidget, QListWidget, QListWidgetItem, QFrame, QScrollArea,
    QFileDialog, QMessageBox, QGroupBox, QButtonGroup
)

from media_downloader.downloader import MediaDownloader
from media_downloader.spotify import SpotifyDownloader
from media_downloader.queue_manager import DownloadQueueManager
from media_downloader.history import (
    load_history, add_history_entry,
    clear_history, clean_missing_history_entries
)
from media_downloader.theme_manager import PALETTES
from media_downloader.downloads_view import DownloadsView
from media_downloader.utils import (
    is_valid_url, get_default_download_dir,
    get_system_clipboard_text, check_ffmpeg_installed
)


# =============================================================================
# ФОНОВЫЕ ПОТОКИ (QTHREAD) С ПРЯМЫМИ СИГНАЛАМИ В ГРАФИЧЕСКИЙ КОНТУР
# =============================================================================

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


# =============================================================================
# ВИДЖЕТ СЕГМЕНТИРОВАННОГО ПЕРЕКЛЮЧАТЕЛЯ (SEGMENTED BUTTON MATERIAL 3)
# =============================================================================

class SegmentedButton(QFrame):
    selectionChanged = pyqtSignal(str)

    def __init__(self, options: List[Any], active: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentedContainer")
        self.buttons: List[QPushButton] = []
        self.items: List[tuple] = []  # (key, display_label)

        for item in options:
            if isinstance(item, (tuple, list)):
                key, label = str(item[0]), str(item[1])
            else:
                key, label = str(item), str(item)
            self.items.append((key, label))

        self._active_key = active or (self.items[0][0] if self.items else "")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        for key, label in self.items:
            btn = QPushButton(label)
            btn.setProperty("segment_key", key)
            btn.setCheckable(True)
            btn.setObjectName("SegmentedBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Гарантируем, что кнопка не ужмётся в раскладке и текст никогда не обрежется
            fm = btn.fontMetrics()
            btn.setMinimumWidth(fm.horizontalAdvance(label) + 24)
            if key == self._active_key:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, k=key: self._on_btn_clicked(k))
            self.btn_group.addButton(btn)
            self.buttons.append(btn)
            layout.addWidget(btn)

    def _on_btn_clicked(self, key: str):
        self._active_key = key
        self.selectionChanged.emit(key)

    def select(self, key: str):
        for btn in self.buttons:
            if btn.property("segment_key") == key:
                self._active_key = key
                btn.setChecked(True)
                self.selectionChanged.emit(key)
                break

    def currentText(self) -> str:
        for btn in self.buttons:
            if btn.isChecked():
                return btn.property("segment_key") or ""
        return self._active_key


# =============================================================================
# QSS СТИЛИЗАЦИЯ ПОД MATERIAL 3
# =============================================================================

def build_app_stylesheet(primary_hex: str, accent_hex: str, hover_hex: str) -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: #11141c;
        color: #e2e8f0;
        font-family: 'Segoe UI', 'Ubuntu', 'Roboto', sans-serif;
        font-size: 13px;
    }}
    QLabel {{
        background-color: transparent;
    }}
    QFrame#Sidebar {{
        background-color: #151821;
        border-right: 1px solid #1f2533;
    }}
    QFrame#Card {{
        background-color: #191d27;
        border: 1px solid #242c3d;
        border-radius: 12px;
    }}
    QFrame#Card QLabel {{
        background-color: transparent;
        background: transparent;
    }}
    QLabel#ThumbLabel, QFrame#Card QLabel#ThumbLabel {{
        background-color: #212634;
        color: #94a3b8;
        border: 1px solid #2d3748;
        border-radius: 8px;
    }}
    QFrame#ProgressCard {{
        background-color: #181c26;
        border: 1px solid #262e40;
        border-radius: 10px;
    }}
    QFrame#ProgressCard QLabel {{
        background-color: transparent;
        background: transparent;
    }}
    QFrame#SuccessBanner {{
        background-color: #064e3b;
        border: 1px solid #059669;
        border-radius: 10px;
    }}
    QFrame#SuccessBanner QLabel {{
        background: transparent;
        background-color: transparent;
        border: none;
    }}
    QFrame#SegmentedContainer {{
        background-color: #151822;
        border: 1px solid #232a3b;
        border-radius: 17px;
        min-height: 34px;
        max-height: 34px;
    }}
    QPushButton#SegmentedBtn {{
        background-color: transparent;
        color: #94a3b8;
        border: 1px solid transparent;
        border-radius: 14px;
        padding: 0px 10px;
        min-height: 28px;
        max-height: 28px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton#SegmentedBtn:checked {{
        background-color: #202b3e;
        color: {accent_hex};
        border: 1px solid {primary_hex};
        font-weight: 500;
    }}
    QPushButton#SegmentedBtn:hover:!checked {{
        background-color: #1a1f2b;
        color: #f1f5f9;
    }}
    QPushButton {{
        background-color: #212634;
        color: #e2e8f0;
        border: 1px solid #2f384a;
        border-radius: 8px;
        padding: 7px 16px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: #293142;
        border-color: #3f4b63;
    }}
    QPushButton:pressed {{
        background-color: #191d28;
    }}
    QPushButton#PrimaryBtn {{
        background-color: {primary_hex};
        color: #ffffff;
        border: none;
        font-weight: bold;
        font-size: 13px;
        border-radius: 8px;
        padding: 9px 20px;
    }}
    QPushButton#PrimaryBtn:hover {{
        background-color: {hover_hex};
    }}
    QPushButton#OutlinedBtn {{
        background-color: #181d27;
        color: {accent_hex};
        border: 1.5px solid {primary_hex};
        border-radius: 8px;
        padding: 8px 18px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton#OutlinedBtn:hover {{
        background-color: #20283a;
    }}
    QPushButton#NavBtn {{
        background-color: transparent;
        color: #94a3b8;
        border: 1px solid transparent;
        border-radius: 19px;
        text-align: left;
        padding: 0 16px;
        min-height: 38px;
        max-height: 38px;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton#NavBtn:hover {{
        background-color: #1c212d;
        color: #f1f5f9;
    }}
    QPushButton#NavBtnActive {{
        background-color: #232e42;
        color: {accent_hex};
        border-left: 3px solid {primary_hex};
        border-radius: 19px;
        text-align: left;
        padding: 0 16px;
        min-height: 38px;
        max-height: 38px;
        font-size: 13px;
        font-weight: bold;
    }}
    QLineEdit {{
        background-color: #171a24;
        color: #ffffff;
        border: 1px solid #273042;
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 13px;
        selection-background-color: {primary_hex};
    }}
    QLineEdit:focus {{
        border: 1.5px solid {accent_hex};
        background-color: #1b202d;
    }}
    QComboBox {{
        background-color: #1a1e2a;
        color: #e2e8f0;
        border: 1px solid #283244;
        border-radius: 8px;
        padding: 6px 12px;
        min-height: 24px;
        font-size: 13px;
    }}
    QComboBox:focus {{
        border: 1.5px solid {primary_hex};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #161923;
        color: #e2e8f0;
        border: 1px solid #2b3548;
        selection-background-color: #232e42;
        selection-color: {accent_hex};
        padding: 4px;
        outline: none;
    }}
    QCheckBox {{
        color: #cbd5e1;
        font-size: 12px;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border-radius: 4px;
        border: 1.5px solid #37435c;
        background-color: #161923;
    }}
    QCheckBox::indicator:checked {{
        background-color: {primary_hex};
        border-color: {accent_hex};
    }}
    QProgressBar {{
        background-color: #212634;
        border: none;
        border-radius: 4px;
        height: 8px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background-color: {accent_hex};
        border-radius: 4px;
    }}
    QListWidget {{
        background-color: #151821;
        border: 1px solid #202635;
        border-radius: 10px;
        padding: 6px;
    }}
    QListWidget::item {{
        background-color: #1c202b;
        border: 1px solid #273042;
        border-radius: 8px;
        padding: 10px;
        margin-bottom: 6px;
    }}
    QListWidget::item:hover {{
        background-color: #222837;
        border-color: #37435c;
    }}
    QScrollBar:vertical {{
        background: #13161e;
        width: 9px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: #2b3345;
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #3f4b64;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QLabel#BadgeChip, QFrame#Card QLabel#BadgeChip {{
        background-color: #212837;
        color: #cbd5e1;
        border: 1px solid #2c364a;
        border-radius: 11px;
        padding: 3px 9px;
        font-size: 11px;
        font-weight: 500;
    }}
    QGroupBox {{
        font-size: 12px;
        font-weight: bold;
        color: #94a3b8;
        border: 1px solid #242c3d;
        border-radius: 10px;
        margin-top: 10px;
        padding-top: 14px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 5px;
    }}
    """


# =============================================================================
# ОКНО ДЛЯ ОТКРЕПЛЕНИЯ СЕРВИСА В ОТДЕЛЬНОЕ ОКНО ОС
# =============================================================================

class DetachedServiceWindow(QMainWindow):
    """
    Позволяет пользователю открепить любое окно сервиса (например, YouTube Плейлист или Spotify)
    в независимое системное окно рабочего стола, а при закрытии — вернуть его обратно.
    """
    def __init__(self, title: str, view_widget: QWidget, on_dock_back_cb: Callable, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Media Downloader Pro — {title}")
        self.resize(960, 780)
        self.setMinimumSize(820, 600)
        self.view_widget = view_widget
        self.on_dock_back_cb = on_dock_back_cb

        # Центральный виджет
        self.setCentralWidget(view_widget)

    def closeEvent(self, event):
        self.on_dock_back_cb(self.view_widget)
        event.accept()


# =============================================================================
# БАЗОВЫЙ КЛАСС ОТДЕЛЬНОГО ОКНА СЕРВИСА / РЕЖИМА
# =============================================================================

class BaseDownloadView(QWidget):
    """
    Базовый независимый экран для конкретного сервиса и режима.
    Изолирует ввод URL, анализ, превью, настройки, фоновые потоки и дашборд прогресса.
    """
    def __init__(
        self,
        title: str,
        icon_str: str,
        downloader: MediaDownloader,
        spotify_downloader: SpotifyDownloader,
        queue_manager: DownloadQueueManager,
        get_cookies_cb: Callable[[], Optional[str]],
        get_speed_limit_cb: Callable[[], Optional[int]],
        on_queue_added_cb: Callable[[], None],
        on_history_added_cb: Callable[[], None],
        on_detach_requested_cb: Optional[Callable[['BaseDownloadView'], None]] = None,
        on_download_started_cb: Optional[Callable[[Any, Dict[str, Any], str, str], None]] = None,
        on_go_to_downloads_cb: Optional[Callable[[], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.view_title = title
        self.view_icon = icon_str
        self.downloader = downloader
        self.spotify_downloader = spotify_downloader
        self.queue_manager = queue_manager
        self.get_cookies_cb = get_cookies_cb
        self.get_speed_limit_cb = get_speed_limit_cb
        self.on_queue_added_cb = on_queue_added_cb
        self.on_history_added_cb = on_history_added_cb
        self.on_detach_requested_cb = on_detach_requested_cb
        self.on_download_started_cb = on_download_started_cb
        self.on_go_to_downloads_cb = on_go_to_downloads_cb

        self.current_analyze_worker: Optional[AnalyzeWorker] = None
        self.current_download_worker: Optional[DownloadWorker] = None
        self.thumb_worker: Optional[ThumbnailWorker] = None
        self._current_source_url = ""
        self._last_downloaded_path = ""
        self.is_detached = False
        self._current_media_info: Optional[Dict[str, Any]] = None

        # Сборка базового контейнера со скроллом
        self._build_base_layout()

    def terminate_workers(self):
        """Безопасное завершение фоновых потоков при закрытии окна."""
        if self.current_analyze_worker and self.current_analyze_worker.isRunning():
            self.current_analyze_worker.terminate()
        if self.current_download_worker and self.current_download_worker.isRunning():
            self.current_download_worker.terminate()
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.terminate()

    def _build_base_layout(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.container = QWidget()
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(20, 16, 20, 16)
        self.content_layout.setSpacing(12)

        # 1. Заголовок окна
        header_row = QHBoxLayout()
        lbl_h = QLabel(f"{self.view_icon}  {self.view_title}")
        lbl_h.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        header_row.addWidget(lbl_h)
        header_row.addStretch()

        self.btn_detach = None
        self.content_layout.addLayout(header_row)

        self.scroll.setWidget(self.container)
        outer_layout.addWidget(self.scroll)

    def _toggle_detach(self):
        if self.on_detach_requested_cb:
            self.on_detach_requested_cb(self)

    # Вспомогательные конструкторы UI элементов
    def _create_url_row(self, placeholder: str):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(placeholder)
        self.url_input.setFixedHeight(40)
        self.url_input.returnPressed.connect(self._on_analyze_clicked)

        btn_clear = QPushButton("✕")
        btn_clear.setFixedSize(36, 40)
        btn_clear.clicked.connect(self._clear_url)

        btn_paste = QPushButton("Вставить")
        btn_paste.setFixedHeight(40)
        btn_paste.clicked.connect(self._paste_url)

        self.btn_analyze = QPushButton("Анализировать")
        self.btn_analyze.setObjectName("PrimaryBtn")
        self.btn_analyze.setFixedHeight(40)
        self.btn_analyze.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_analyze.clicked.connect(self._on_analyze_clicked)

        row.addWidget(self.url_input, 1)
        row.addWidget(btn_clear)
        row.addWidget(btn_paste)
        row.addWidget(self.btn_analyze)
        self.content_layout.addLayout(row)

        self.url_input.textChanged.connect(self._on_url_text_changed)

    def _on_analyze_clicked(self):
        if hasattr(self, "success_banner") and self.success_banner is not None:
            self.success_banner.setVisible(False)
        self.start_analyze()

    def _clear_url(self):
        """Очищает поле ввода ссылки и удаляет превью."""
        self.url_input.clear()
        self.reset_preview()

    def _on_url_text_changed(self, text: Optional[str] = None):
        """
        Срабатывает при изменении ссылки:
        если ссылка стёрта или изменена, превью удаляется.
        """
        if hasattr(self, "success_banner") and self.success_banner is not None:
            self.success_banner.setVisible(False)
        txt = self.url_input.text().strip() if hasattr(self, "url_input") else ""
        if not txt:
            self.reset_preview()
        elif self._current_source_url and txt != self._current_source_url:
            self.reset_preview()

    def reset_preview(self):
        """
        Сбрасывает превью, обложку и информацию о медиа в чистое исходное состояние
        при стирании или очистке ссылки.
        """
        if hasattr(self, "success_banner") and self.success_banner is not None:
            self.success_banner.setVisible(False)

        # Завершаем фоновые потоки анализа и загрузки обложки, если они выполняются
        if self.thumb_worker and self.thumb_worker.isRunning():
            try:
                self.thumb_worker.terminate()
            except Exception:
                pass
            self.thumb_worker = None

        if self.current_analyze_worker and self.current_analyze_worker.isRunning():
            try:
                self.current_analyze_worker.terminate()
            except Exception:
                pass
            self.current_analyze_worker = None

        self._current_source_url = ""
        self._current_media_info = None

        # Очищаем превью / обложку (удаляем pixmap и возвращаем плейсхолдер)
        if hasattr(self, "thumb_lbl") and self.thumb_lbl is not None:
            self.thumb_lbl.clear()
            if getattr(self, "_is_preview_square", False):
                self.thumb_lbl.setText("🎵\nНет обложки")
            else:
                self.thumb_lbl.setText("🎬\nНет превью")

        # Возвращаем исходный текст описания
        if hasattr(self, "title_lbl") and self.title_lbl is not None:
            self.title_lbl.setText("Вставьте ссылку и нажмите «Анализировать»")

        if hasattr(self, "author_lbl") and self.author_lbl is not None:
            self.author_lbl.setText("Автор / Исполнитель: --")

        if hasattr(self, "dur_badge") and self.dur_badge is not None:
            self.dur_badge.setText("⏱ --:--")

        if hasattr(self, "platform_badge") and self.platform_badge is not None:
            service_name = self.view_title.split("—")[0].strip()
            self.platform_badge.setText(f"Сервис: {service_name}")

        if hasattr(self, "btn_open_browser") and self.btn_open_browser is not None:
            self.btn_open_browser.setEnabled(False)

        # Сбрасываем кнопки действий
        if hasattr(self, "btn_analyze") and self.btn_analyze is not None:
            self.btn_analyze.setEnabled(True)

        if hasattr(self, "btn_download") and self.btn_download is not None:
            self.btn_download.setEnabled(False)

        if hasattr(self, "btn_queue") and self.btn_queue is not None:
            self.btn_queue.setEnabled(False)

        # Сбрасываем прогресс и статус, если сейчас не выполняется скачивание
        if not (self.current_download_worker and self.current_download_worker.isRunning()):
            if hasattr(self, "progress_bar") and self.progress_bar is not None:
                self.progress_bar.setRange(0, 1000)
                self.progress_bar.setValue(0)

            if hasattr(self, "percent_lbl") and self.percent_lbl is not None:
                self.percent_lbl.setText("0.0%")

            if hasattr(self, "status_lbl") and self.status_lbl is not None:
                self.status_lbl.setText("Готов к работе")

            if hasattr(self, "speed_lbl") and self.speed_lbl is not None:
                self.speed_lbl.setText("⚡ -- МБ/с")

            if hasattr(self, "size_lbl") and self.size_lbl is not None:
                self.size_lbl.setText("💾 -- / --")

            if hasattr(self, "eta_lbl") and self.eta_lbl is not None:
                self.eta_lbl.setText("⏱ ETA: --:--")

            if hasattr(self, "success_banner") and self.success_banner is not None:
                self.success_banner.setVisible(False)

        # Очищаем специфичные контролы подклассов
        if hasattr(self, "cmb_res") and self.cmb_res is not None:
            self.cmb_res.clear()
            self.cmb_res.addItem("None")
            self.cmb_res.setEnabled(False)

        if hasattr(self, "grp_playlist") and self.grp_playlist is not None:
            self.grp_playlist.setVisible(False)
            if hasattr(self, "list_entries") and self.list_entries is not None:
                self.list_entries.clear()

        if hasattr(self, "grp_tracks") and self.grp_tracks is not None:
            self.grp_tracks.setVisible(False)
            if hasattr(self, "list_tracks") and self.list_tracks is not None:
                self.list_tracks.clear()

        if hasattr(self, "grp_meta") and self.grp_meta is not None:
            if hasattr(self, "txt_artist") and self.txt_artist is not None:
                self.txt_artist.clear()
            if hasattr(self, "txt_title") and self.txt_title is not None:
                self.txt_title.clear()
            if hasattr(self, "txt_album") and self.txt_album is not None:
                self.txt_album.clear()

    clear_preview = reset_preview

    def _paste_url(self):
        txt = ""
        try:
            cb = QApplication.clipboard()
            if cb:
                txt = cb.text().strip()
        except Exception:
            pass
        if not txt:
            txt = get_system_clipboard_text().strip()

        if txt:
            norm = txt
            if not norm.startswith(("http://", "https://")):
                for domain in ["youtube.com", "youtu.be", "tiktok.com", "spotify.com", "soundcloud.com", "vk.com", "rutube.ru", "instagram.com", "twitch.tv"]:
                    if norm.lower().startswith((domain, "www." + domain)):
                        norm = "https://" + norm
                        break
            self.url_input.setText(norm)
            self.start_analyze()

    def _create_preview_card(self, is_square: bool = False):
        self._is_preview_square = is_square
        self.preview_card = QFrame()
        self.preview_card.setObjectName("Card")
        preview_layout = QHBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(16)

        self.thumb_lbl = QLabel()
        self.thumb_lbl.setObjectName("ThumbLabel")
        if is_square:
            self.thumb_lbl.setFixedSize(100, 100)
            self.thumb_lbl.setText("🎵\nНет обложки")
        else:
            self.thumb_lbl.setFixedSize(150, 95)
            self.thumb_lbl.setText("🎬\nНет превью")
        self.thumb_lbl.setStyleSheet(
            "background-color: #212634; color: #94a3b8; border: 1px solid #2d3748; border-radius: 8px; font-size: 11px; font-weight: 500;"
        )
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_lbl.setWordWrap(True)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(6)
        self.title_lbl = QLabel("Вставьте ссылку и нажмите «Анализировать»")
        self.title_lbl.setStyleSheet("font-size: 14.5px; font-weight: bold; color: #ffffff; background-color: transparent;")
        self.title_lbl.setWordWrap(True)

        self.author_lbl = QLabel("Автор / Исполнитель: --")
        self.author_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; background-color: transparent;")

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        self.dur_badge = QLabel("⏱ --:--")
        self.dur_badge.setObjectName("BadgeChip")
        self.platform_badge = QLabel(f"Сервис: {self.view_title.split('—')[0].strip()}")
        self.platform_badge.setObjectName("BadgeChip")

        self.btn_open_browser = QPushButton("В источнике ↗")
        self.btn_open_browser.setStyleSheet("background-color: transparent; border: none; color: #38bdf8; font-size: 11.5px; font-weight: bold;")
        self.btn_open_browser.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_browser.setEnabled(False)
        self.btn_open_browser.clicked.connect(self._open_in_browser)

        badge_row.addWidget(self.dur_badge)
        badge_row.addWidget(self.platform_badge)
        badge_row.addWidget(self.btn_open_browser)
        badge_row.addStretch()

        meta_col.addWidget(self.title_lbl)
        meta_col.addWidget(self.author_lbl)
        meta_col.addLayout(badge_row)

        preview_layout.addWidget(self.thumb_lbl)
        preview_layout.addLayout(meta_col, 1)
        self.content_layout.addWidget(self.preview_card)

    def _create_folder_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder_input = QLineEdit(get_default_download_dir())
        self.folder_input.setFixedHeight(38)

        btn_browse = QPushButton("📁 Обзор...")
        btn_browse.setFixedHeight(38)
        btn_browse.clicked.connect(lambda: self._browse_folder(self.folder_input))

        btn_open = QPushButton("Открыть")
        btn_open.setFixedHeight(38)
        btn_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder_input.text())))

        row.addWidget(self.folder_input, 1)
        row.addWidget(btn_browse)
        row.addWidget(btn_open)
        self.content_layout.addLayout(row)

    def _browse_folder(self, line_edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения", line_edit.text())
        if folder:
            line_edit.setText(folder)

    def _create_progress_card(self):
        self.progress_card = QFrame()
        self.progress_card.setObjectName("ProgressCard")
        prog_layout = QVBoxLayout(self.progress_card)
        prog_layout.setContentsMargins(14, 12, 14, 12)
        prog_layout.setSpacing(8)

        top_prog_row = QHBoxLayout()
        self.status_lbl = QLabel("Готов к работе")
        self.status_lbl.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")
        self.percent_lbl = QLabel("0.0%")
        self.percent_lbl.setStyleSheet("font-size: 12.5px; font-weight: bold; color: #38bdf8;")
        top_prog_row.addWidget(self.status_lbl)
        top_prog_row.addStretch()
        top_prog_row.addWidget(self.percent_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)

        metrics_row = QHBoxLayout()
        self.speed_lbl = QLabel("⚡ -- МБ/с")
        self.speed_lbl.setStyleSheet("color: #38bdf8; font-size: 11px;")

        self.size_lbl = QLabel("💾 -- / --")
        self.size_lbl.setStyleSheet("color: #c084fc; font-size: 11px;")

        self.eta_lbl = QLabel("⏱ ETA: --:--")
        self.eta_lbl.setStyleSheet("color: #fbbf24; font-size: 11px;")

        metrics_row.addWidget(self.speed_lbl)
        metrics_row.addStretch()
        metrics_row.addWidget(self.size_lbl)
        metrics_row.addStretch()
        metrics_row.addWidget(self.eta_lbl)

        prog_layout.addLayout(top_prog_row)
        prog_layout.addWidget(self.progress_bar)
        prog_layout.addLayout(metrics_row)
        self.content_layout.addWidget(self.progress_card)

    def _create_actions_row(self, download_text: str = "Скачать"):
        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.btn_download = QPushButton(f"⬇️  {download_text}")
        self.btn_download.setObjectName("PrimaryBtn")
        self.btn_download.setFixedHeight(44)
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self.start_download)

        self.btn_queue = QPushButton("➕  В очередь")
        self.btn_queue.setObjectName("OutlinedBtn")
        self.btn_queue.setFixedHeight(44)
        self.btn_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_queue.setEnabled(False)
        self.btn_queue.clicked.connect(self.add_to_queue)

        actions_row.addWidget(self.btn_download, 2)
        actions_row.addWidget(self.btn_queue, 1)
        self.content_layout.addLayout(actions_row)

        # Баннер успешной загрузки
        self.success_banner = QFrame()
        self.success_banner.setObjectName("SuccessBanner")
        self.success_banner.setVisible(False)
        ban_layout = QHBoxLayout(self.success_banner)
        ban_layout.setContentsMargins(14, 8, 14, 8)
        ban_layout.setSpacing(10)

        lbl_ok = QLabel("✓ Файл успешно загружен!")
        lbl_ok.setStyleSheet("background: transparent; border: none; font-weight: bold; color: #34d399; font-size: 13px;")

        btn_banner_style = """
            QPushButton {
                background-color: #065f46;
                color: #ffffff;
                border: 1px solid #10b981;
                border-radius: 6px;
                font-size: 11.5px;
                font-weight: 600;
                padding: 4px 13px;
            }
            QPushButton:hover {
                background-color: #047857;
                border-color: #34d399;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #064e3b;
            }
        """

        btn_open_file = QPushButton("📂 Открыть")
        btn_open_file.setFixedHeight(30)
        btn_open_file.setStyleSheet(btn_banner_style)
        btn_open_file.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_file.clicked.connect(self._open_downloaded_file)

        btn_open_dir = QPushButton("📁 В папке")
        btn_open_dir.setFixedHeight(30)
        btn_open_dir.setStyleSheet(btn_banner_style)
        btn_open_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_dir.clicked.connect(self._open_downloaded_folder)

        btn_go_downloads = QPushButton("⚡ Загрузки")
        btn_go_downloads.setFixedHeight(30)
        btn_go_downloads.setStyleSheet(btn_banner_style)
        btn_go_downloads.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go_downloads.setToolTip("Перейти в раздел активных загрузок")
        btn_go_downloads.clicked.connect(self._go_to_downloads)

        btn_close_banner = QPushButton("✕")
        btn_close_banner.setFixedSize(26, 30)
        btn_close_banner.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close_banner.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #a7f3d0;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                color: #ffffff;
                background-color: rgba(255, 255, 255, 0.15);
            }
        """)
        btn_close_banner.clicked.connect(lambda: self.success_banner.setVisible(False))

        ban_layout.addWidget(lbl_ok)
        ban_layout.addStretch()
        ban_layout.addWidget(btn_open_file)
        ban_layout.addWidget(btn_open_dir)
        ban_layout.addWidget(btn_go_downloads)
        ban_layout.addWidget(btn_close_banner)
        self.content_layout.addWidget(self.success_banner)

    def _go_to_downloads(self):
        if self.on_go_to_downloads_cb:
            self.on_go_to_downloads_cb()

    def _start_download_worker(self, opts: dict, media_title: str = "", format_str: str = ""):
        if hasattr(self, "success_banner") and self.success_banner is not None:
            self.success_banner.setVisible(False)
        self.btn_download.setEnabled(False)
        self.btn_queue.setEnabled(False)
        self.btn_analyze.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.status_lbl.setText("Запуск загрузки...")
        self.percent_lbl.setText("Запуск...")
        self.speed_lbl.setText("⚡ Подключение...")

        self.current_download_worker = DownloadWorker(self.downloader, self.spotify_downloader, opts)
        self.current_download_worker.sig_progress.connect(self._handle_download_progress)
        self.current_download_worker.sig_status.connect(self._handle_download_status)
        self.current_download_worker.sig_finished.connect(self._handle_download_finished)
        self.current_download_worker.sig_error.connect(self._handle_download_error)

        title = media_title or (self.title_lbl.text() if hasattr(self, "title_lbl") and self.title_lbl.text() != "Вставьте ссылку и нажмите «Анализировать»" else "Медиафайл")
        if self.on_download_started_cb:
            self.on_download_started_cb(self.current_download_worker, opts, title, format_str)

        self.current_download_worker.start()

    def _open_in_browser(self):
        url = self._current_source_url or self.url_input.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_downloaded_file(self):
        if self._last_downloaded_path and os.path.exists(self._last_downloaded_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_downloaded_path))
        else:
            self._open_downloaded_folder()

    def _open_downloaded_folder(self):
        folder = self.folder_input.text().strip()
        if not folder or not os.path.exists(folder):
            folder = os.path.dirname(self._last_downloaded_path) if self._last_downloaded_path else get_default_download_dir()
        if os.path.exists(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_thumb_loaded(self, pixmap: QPixmap, is_square: bool = False):
        w_target = 100 if is_square else 150
        h_target = 100 if is_square else 95
        scaled = pixmap.scaled(w_target, h_target, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - w_target) // 2)
        y = max(0, (scaled.height() - h_target) // 2)
        cropped = scaled.copy(x, y, w_target, h_target)

        rounded = QPixmap(w_target, h_target)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w_target, h_target, 8, 8)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()

        self.thumb_lbl.setPixmap(rounded)

    # Методы обновления прогресса
    def _handle_download_progress(self, p_data: dict):
        frac = p_data.get("fraction", 0.0)
        pct = p_data.get("percent", frac * 100.0)
        spd = p_data.get("speed_str", "-- МБ/с")
        dld = p_data.get("downloaded_str", "--")
        tot = p_data.get("total_str", "--")
        eta = p_data.get("eta_str", "--:--")

        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(int(frac * 1000))
        self.percent_lbl.setText(f"{pct:.1f}%")
        self.status_lbl.setText(f"Загрузка: {pct:.1f}% | Скорость: {spd} | ETA: {eta}")
        self.speed_lbl.setText(f"⚡ {spd}")
        self.size_lbl.setText(f"💾 {dld} / {tot}")
        self.eta_lbl.setText(f"⏱ ETA: {eta}")

    def _handle_download_status(self, text: str):
        self.status_lbl.setText(text)

    def _handle_download_finished(self, res: dict):
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.btn_analyze.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.percent_lbl.setText("100%")
        self.status_lbl.setText("Загрузка успешно завершена!")
        self._last_downloaded_path = res.get("file_path", "") if isinstance(res, dict) else ""
        self.success_banner.setVisible(True)
        try:
            self.on_history_added_cb()
        except Exception as e:
            print(f"[!] Ошибка обновления значка истории: {e}")

    def _handle_download_error(self, err_msg: str):
        self.btn_download.setEnabled(True)
        self.btn_queue.setEnabled(True)
        self.btn_analyze.setEnabled(True)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.percent_lbl.setText("0%")
        clean_msg = str(err_msg).strip()
        short_err = clean_msg.splitlines()[-1] if clean_msg else "Произошла ошибка"
        self.status_lbl.setText(f"Ошибка: {short_err[:45]}")
        try:
            display_err = clean_msg[:700] + ("..." if len(clean_msg) > 700 else "")
            QMessageBox.critical(self, "Ошибка скачивания", f"Не удалось загрузить медиа:\n{display_err}")
        except Exception:
            pass

    # Заглушки для переопределения в наследниках
    def start_analyze(self):
        pass

    def start_download(self):
        pass

    def add_to_queue(self):
        pass


# =============================================================================
# РАЗДЕЛ ВИДЕО: 1. YOUTUBE — ОДИНОЧНОЕ ВИДЕО
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ ВИДЕО: 2. YOUTUBE — ПЛЕЙЛИСТ И КАНАЛ
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ ВИДЕО: 3. TIKTOK — КЛИПЫ И ОРИГИНАЛЬНЫЙ ЗВУК
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ ВИДЕО: 4. ДРУГИЕ СЕРВИСЫ (VK, RUTUBE, TWITCH, REELS И ДР.)
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ МУЗЫКА: 1. SPOTIFY — ОДИНОЧНЫЙ ТРЕК
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ МУЗЫКА: 2. SPOTIFY — АЛЬБОМ И ПЛЕЙЛИСТ
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ МУЗЫКА: 3. SOUNDCLOUD (ТРЕК ИЛИ ПЛЕЙЛИСТ)
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ МУЗЫКА: 4. YOUTUBE MUSIC (ТРЕК ИЛИ АЛЬБОМ)
# =============================================================================

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


# =============================================================================
# РАЗДЕЛ МУЗЫКА: 5. ДРУГИЕ АУДИО СЕРВИСЫ (BANDCAMP, WEB RADIO, ДР.)
# =============================================================================

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


# =============================================================================
# ХАБ РАЗДЕЛА: ВИДЕО (ПЕРЕКЛЮЧЕНИЕ СЕРВИСОВ И РЕЖИМОВ МЕЖДУ ОТДЕЛЬНЫМИ ОКНАМИ)
# =============================================================================

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


# =============================================================================
# ХАБ РАЗДЕЛА: МУЗЫКА (ПЕРЕКЛЮЧЕНИЕ СЕРВИСОВ И РЕЖИМОВ МЕЖДУ ОТДЕЛЬНЫМИ ОКНАМИ)
# =============================================================================

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


# =============================================================================
# ГЛАВНОЕ ОКНО ПРИЛОЖЕНИЯ
# =============================================================================

class MediaDownloaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Downloader Pro")
        self.resize(1140, 850)
        self.setMinimumSize(980, 700)

        # Модели данных
        self.downloader = MediaDownloader()
        self.spotify_downloader = SpotifyDownloader()
        self.queue_manager = DownloadQueueManager()

        # Активная цветовая палитра
        self.current_palette_name = "Ocean Blue"
        self.palette = PALETTES[self.current_palette_name]

        # Открепленные окна
        self.detached_windows: Dict[QWidget, DetachedServiceWindow] = {}

        # Таймер и нативный сигнал буфера обмена
        self.clipboard_monitor_active = False
        self.last_clipboard_url = ""
        self.clipboard_timer = QTimer(self)
        self.clipboard_timer.timeout.connect(self._check_clipboard)
        try:
            cb = QApplication.clipboard()
            if cb:
                cb.dataChanged.connect(self._on_clipboard_data_changed)
        except Exception:
            pass

        # Сборка UI
        self._build_ui()
        self._apply_theme()
        self._refresh_history_badge()
        self._refresh_queue_badge()

    def closeEvent(self, event):
        """Гарантированное мгновенное закрытие приложения по Alt+F4 или крестику."""
        self.clipboard_timer.stop()

        # Завершение потоков во всех окнах
        for v in self.video_hub.get_all_views():
            v.terminate_workers()
        for v in self.music_hub.get_all_views():
            v.terminate_workers()

        if hasattr(self, "current_queue_worker") and self.current_queue_worker and self.current_queue_worker.isRunning():
            self.current_queue_worker.terminate()

        if hasattr(self, "downloads_view"):
            for card in self.downloads_view.download_cards.values():
                if card.worker and card.worker.isRunning():
                    try:
                        card.worker.terminate()
                    except Exception:
                        pass

        # Закрываем открепленные окна
        for w in list(self.detached_windows.values()):
            try:
                w.close()
            except Exception:
                pass

        event.accept()
        try:
            os._exit(0)
        except Exception:
            sys.exit(0)

    # -------------------------------------------------------------------------
    # РАЗМЕТКА И СТИЛИЗАЦИЯ
    # -------------------------------------------------------------------------

    def _build_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Сайдбар слева
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)

        # Рабочая область справа
        self.stack = QStackedWidget()

        self.downloads_view = DownloadsView(parent=self)
        self.downloads_view.sig_active_count_changed.connect(lambda cnt: self._update_nav_buttons(self.stack.currentIndex()))

        self.video_hub = VideoHubView(
            downloader=self.downloader,
            spotify_downloader=self.spotify_downloader,
            queue_manager=self.queue_manager,
            get_cookies_cb=self._get_cookies,
            get_speed_limit_cb=self._get_speed_limit,
            on_queue_added_cb=self._refresh_queue_badge,
            on_history_added_cb=self._refresh_history_badge,
            on_detach_requested_cb=self._handle_view_detach,
            on_download_started_cb=self._on_download_started,
            on_go_to_downloads_cb=lambda: self._switch_nav(2),
        )

        self.music_hub = MusicHubView(
            downloader=self.downloader,
            spotify_downloader=self.spotify_downloader,
            queue_manager=self.queue_manager,
            get_cookies_cb=self._get_cookies,
            get_speed_limit_cb=self._get_speed_limit,
            on_queue_added_cb=self._refresh_queue_badge,
            on_history_added_cb=self._refresh_history_badge,
            on_detach_requested_cb=self._handle_view_detach,
            on_download_started_cb=self._on_download_started,
            on_go_to_downloads_cb=lambda: self._switch_nav(2),
        )

        self.page_queue = self._create_queue_page()
        self.page_history = self._create_history_page()

        self.stack.addWidget(self.video_hub)       # 0
        self.stack.addWidget(self.music_hub)       # 1
        self.stack.addWidget(self.downloads_view)  # 2
        self.stack.addWidget(self.page_queue)      # 3
        self.stack.addWidget(self.page_history)    # 4

        main_layout.addWidget(self.stack, 1)

    def _on_download_started(self, worker: Any, options: dict, title: str, format_str: str):
        if hasattr(self, "downloads_view"):
            self.downloads_view.add_download(worker, options, title=title, format_str=format_str)
            self._update_nav_buttons(self.stack.currentIndex())

    def _handle_view_detach(self, view_widget: BaseDownloadView):
        """Открепление окна сервиса в отдельное плавающее системное окно или возврат."""
        if view_widget in self.detached_windows:
            # Уже откреплен, закрываем и возвращаем
            dw = self.detached_windows[view_widget]
            dw.close()
            return

        # Находим родительский QStackedWidget
        parent_stack = None
        if view_widget in self.video_hub.get_all_views():
            parent_stack = self.video_hub.stack
        elif view_widget in self.music_hub.get_all_views():
            parent_stack = self.music_hub.stack

        if parent_stack:
            idx = parent_stack.indexOf(view_widget)
            parent_stack.removeWidget(view_widget)

            def on_re_dock(w):
                if parent_stack and w:
                    parent_stack.insertWidget(idx, w)
                    parent_stack.setCurrentWidget(w)
                    if getattr(w, "btn_detach", None):
                        w.btn_detach.setText("↗ Открыть в отдельном окне")
                    w.is_detached = False
                    if w in self.detached_windows:
                        del self.detached_windows[w]

            dw = DetachedServiceWindow(
                title=f"{view_widget.view_icon} {view_widget.view_title}",
                view_widget=view_widget,
                on_dock_back_cb=on_re_dock,
                parent=None
            )
            pri = self.palette.get("primary", "#1F6AA5")
            acc = self.palette.get("accent", "#3B8ED0")
            hov = self.palette.get("hover", "#144870")
            dw.setStyleSheet(build_app_stylesheet(pri, acc, hov))

            if getattr(view_widget, "btn_detach", None):
                view_widget.btn_detach.setText("↙ Вернуть в главное окно")
            view_widget.is_detached = True
            self.detached_windows[view_widget] = dw
            dw.show()

    def _apply_theme(self):
        pri = self.palette.get("primary", "#1F6AA5")
        acc = self.palette.get("accent", "#3B8ED0")
        hov = self.palette.get("hover", "#144870")
        qss = build_app_stylesheet(pri, acc, hov)
        self.setStyleSheet(qss)
        for dw in self.detached_windows.values():
            dw.setStyleSheet(qss)

    def _on_palette_changed(self, name: str):
        if name in PALETTES:
            self.current_palette_name = name
            self.palette = PALETTES[name]
            self._apply_theme()
            self._update_nav_buttons(self.stack.currentIndex())

    # -------------------------------------------------------------------------
    # САЙДБАР (SIDEBAR)
    # -------------------------------------------------------------------------

    def _create_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(250)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        # Брендинг
        brand_row = QHBoxLayout()
        lbl_icon = QLabel("⬇️")
        lbl_icon.setStyleSheet("font-size: 20px;")
        lbl_brand = QLabel("Media Downloader")
        lbl_brand.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        brand_row.addWidget(lbl_icon)
        brand_row.addWidget(lbl_brand)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        lbl_sub = QLabel("Pro Desktop Edition")
        lbl_sub.setStyleSheet("font-size: 10.5px; color: #64748b; margin-left: 28px; margin-bottom: 12px;")
        layout.addWidget(lbl_sub)

        # Заголовок раздела
        lbl_sec1 = QLabel("ОСНОВНЫЕ РАЗДЕЛЫ")
        lbl_sec1.setStyleSheet("font-size: 9.5px; font-weight: bold; color: #64748b; margin-top: 6px; margin-bottom: 4px;")
        layout.addWidget(lbl_sec1)

        # Пилюлевидные кнопки навигации
        self.nav_btns = []
        nav_items = [
            ("🎬  Видео", 0),
            ("🎧  Музыка", 1),
            ("⚡  Загрузки", 2),
            ("📥  Очередь", 3),
            ("📜  История", 4),
        ]
        for title, idx in nav_items:
            btn = QPushButton(title)
            btn.setObjectName("NavBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(38)
            btn.clicked.connect(lambda checked, i=idx: self._switch_nav(i))
            layout.addWidget(btn)
            self.nav_btns.append(btn)

        self._update_nav_buttons(0)

        # Разделитель
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #1f2533; margin: 8px 0;")
        layout.addWidget(sep1)

        # Раздел настроек
        lbl_sec2 = QLabel("СЕТЬ И ОПЦИИ")
        lbl_sec2.setStyleSheet("font-size: 9.5px; font-weight: bold; color: #64748b;")
        layout.addWidget(lbl_sec2)

        self.chk_clipboard = QCheckBox("Авто-вставка URL")
        self.chk_clipboard.toggled.connect(self._toggle_clipboard_watcher)
        layout.addWidget(self.chk_clipboard)

        lbl_spd = QLabel("Лимит скорости:")
        lbl_spd.setStyleSheet("font-size: 11px; color: #94a3b8; margin-top: 2px;")
        layout.addWidget(lbl_spd)
        self.cmb_speed = QComboBox()
        self.cmb_speed.addItems(["Без ограничений", "1 МБ/с", "2 МБ/с", "5 МБ/с", "10 МБ/с"])
        layout.addWidget(self.cmb_speed)

        lbl_cookies = QLabel("Cookies браузера:")
        lbl_cookies.setStyleSheet("font-size: 11px; color: #94a3b8; margin-top: 2px;")
        layout.addWidget(lbl_cookies)
        self.cmb_cookies = QComboBox()
        self.cmb_cookies.addItems(["Без cookies", "chrome", "firefox", "edge", "brave", "opera"])
        layout.addWidget(self.cmb_cookies)

        lbl_pal = QLabel("Цветовая палитра:")
        lbl_pal.setStyleSheet("font-size: 11px; color: #94a3b8; margin-top: 2px;")
        layout.addWidget(lbl_pal)
        self.cmb_palette = QComboBox()
        for p in PALETTES.keys():
            self.cmb_palette.addItem(p)
        self.cmb_palette.currentTextChanged.connect(self._on_palette_changed)
        layout.addWidget(self.cmb_palette)

        layout.addStretch()

        # Статус FFmpeg внизу сайдбара
        is_ff = check_ffmpeg_installed()
        ff_text = "✓ FFmpeg подключен" if is_ff else "⚠ FFmpeg не найден"
        ff_color = "#34d399" if is_ff else "#f87171"
        self.btn_ffmpeg = QPushButton(ff_text)
        self.btn_ffmpeg.setStyleSheet(f"background-color: transparent; border: 1px solid {ff_color}; color: {ff_color}; border-radius: 7px; font-size: 11px; font-weight: 600; padding: 5px;")
        layout.addWidget(self.btn_ffmpeg)

        lbl_ver = QLabel("Media Downloader Pro v4.0")
        lbl_ver.setStyleSheet("font-size: 10px; color: #475569; text-align: center; margin-top: 4px;")
        lbl_ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_ver)

        return frame

    def _switch_nav(self, index: int):
        self.stack.setCurrentIndex(index)
        self._update_nav_buttons(index)
        if index == 2:
            if hasattr(self, "downloads_view"):
                self.downloads_view.refresh_view()
        elif index == 3:
            self._render_queue_list()
        elif index == 4:
            self._render_history_list()

    def _update_nav_buttons(self, active_index: int):
        d_count = self.downloads_view.get_active_count() if hasattr(self, "downloads_view") else 0
        q_count = len(self.queue_manager.get_tasks())
        h_count = len(load_history())

        base_titles = [
            "🎬  Видео",
            "🎧  Музыка",
            f"⚡  Загрузки  ({d_count})" if d_count > 0 else "⚡  Загрузки",
            f"📥  Очередь  ({q_count})" if q_count > 0 else "📥  Очередь",
            f"📜  История  ({h_count})" if h_count > 0 else "📜  История",
        ]

        for i, btn in enumerate(self.nav_btns):
            if i < len(base_titles):
                btn.setText(base_titles[i])
            if i == active_index:
                btn.setObjectName("NavBtnActive")
            else:
                btn.setObjectName("NavBtn")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_history_badge(self):
        self._update_nav_buttons(self.stack.currentIndex())

    def _refresh_queue_badge(self):
        self._update_nav_buttons(self.stack.currentIndex())

    def _get_speed_limit(self) -> Optional[int]:
        txt = self.cmb_speed.currentText()
        if "1 МБ" in txt:
            return 1024 * 1024
        elif "2 МБ" in txt:
            return 2 * 1024 * 1024
        elif "5 МБ" in txt:
            return 5 * 1024 * 1024
        elif "10 МБ" in txt:
            return 10 * 1024 * 1024
        return None

    def _get_cookies(self) -> Optional[str]:
        val = self.cmb_cookies.currentText()
        return None if val == "Без cookies" else val

    # -------------------------------------------------------------------------
    # МОНИТОРИНГ БУФЕРА ОБМЕНА
    # -------------------------------------------------------------------------

    def _toggle_clipboard_watcher(self, active: bool):
        self.clipboard_monitor_active = active
        if active:
            self.clipboard_timer.start(1000)
            self._check_clipboard(force=True)
        else:
            self.clipboard_timer.stop()

    def _on_clipboard_data_changed(self):
        if self.clipboard_monitor_active:
            self._check_clipboard()

    def _check_clipboard(self, force: bool = False):
        if not self.clipboard_monitor_active:
            return
        text = ""
        try:
            cb = QApplication.clipboard()
            if cb:
                text = cb.text().strip()
        except Exception:
            pass
        if not text:
            text = get_system_clipboard_text().strip()

        if not text:
            return

        norm_text = text
        if not norm_text.startswith(("http://", "https://")):
            for domain in ["youtube.com", "youtu.be", "tiktok.com", "spotify.com", "soundcloud.com", "vk.com", "rutube.ru", "instagram.com", "twitch.tv"]:
                if norm_text.lower().startswith((domain, "www." + domain)):
                    norm_text = "https://" + norm_text
                    break

        if is_valid_url(norm_text):
            if force or norm_text != self.last_clipboard_url:
                self.last_clipboard_url = norm_text
                self._handle_clipboard_url(norm_text)

    def _handle_clipboard_url(self, url: str):
        """Интеллектуальная маршрутизация ссылки прямо в нужное отдельное окно."""
        u_lower = url.lower()
        if "spotify.com" in u_lower:
            self._switch_nav(1)
            is_pl = any(x in u_lower for x in ["playlist", "album", "artist"])
            self.music_hub.switch_to("Spotify", is_playlist=is_pl)
            target_view = self.music_hub.view_sp_playlist if is_pl else self.music_hub.view_sp_track
            target_view.url_input.setText(url)
            target_view.start_analyze()
        elif "soundcloud.com" in u_lower:
            self._switch_nav(1)
            is_pl = "sets" in u_lower
            self.music_hub.switch_to("SoundCloud", is_playlist=is_pl)
            target_view = self.music_hub.view_sc_playlist if is_pl else self.music_hub.view_sc_track
            target_view.url_input.setText(url)
            target_view.start_analyze()
        elif "music.youtube.com" in u_lower:
            self._switch_nav(1)
            is_pl = "list=" in u_lower
            self.music_hub.switch_to("YouTube Music", is_playlist=is_pl)
            target_view = self.music_hub.view_ytm_playlist if is_pl else self.music_hub.view_ytm_track
            target_view.url_input.setText(url)
            target_view.start_analyze()
        elif "tiktok.com" in u_lower:
            self._switch_nav(0)
            self.video_hub.switch_to("TikTok")
            self.video_hub.view_tiktok.url_input.setText(url)
            self.video_hub.view_tiktok.start_analyze()
        elif "youtube.com" in u_lower or "youtu.be" in u_lower:
            self._switch_nav(0)
            is_pl = "list=" in u_lower and "watch" not in u_lower
            self.video_hub.switch_to("YouTube", is_playlist=is_pl)
            target_view = self.video_hub.view_yt_playlist if is_pl else self.video_hub.view_yt_single
            target_view.url_input.setText(url)
            target_view.start_analyze()
        else:
            self._switch_nav(0)
            self.video_hub.switch_to("Другие сервисы")
            self.video_hub.view_other_single.url_input.setText(url)
            self.video_hub.view_other_single.start_analyze()

    # -------------------------------------------------------------------------
    # СТРАНИЦА: ОЧЕРЕДЬ ЗАГРУЗОК
    # -------------------------------------------------------------------------

    def _create_queue_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self.queue_header_lbl = QLabel("Очередь задач")
        self.queue_header_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")

        self.btn_start_queue = QPushButton("▶️ Запустить очередь")
        self.btn_start_queue.setObjectName("PrimaryBtn")
        self.btn_start_queue.clicked.connect(self._process_queue_batch)

        btn_clear_queue = QPushButton("🗑️ Очистить")
        btn_clear_queue.clicked.connect(self._clear_queue)

        top_row.addWidget(self.queue_header_lbl)
        top_row.addStretch()
        top_row.addWidget(self.btn_start_queue)
        top_row.addWidget(btn_clear_queue)
        layout.addLayout(top_row)

        self.queue_list_widget = QListWidget()
        layout.addWidget(self.queue_list_widget)
        return widget

    def _render_queue_list(self):
        self.queue_list_widget.clear()
        tasks = self.queue_manager.get_tasks()
        self.queue_header_lbl.setText(f"Очередь задач ({len(tasks)})")

        if not tasks:
            item = QListWidgetItem("Очередь пуста. Нажмите «➕ В очередь» в любом окне загрузки.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.queue_list_widget.addItem(item)
            return

        for task in tasks:
            status_text = {
                "pending": "⏳ В ожидании",
                "downloading": f"⬇️ Скачивание: {task.progress_percent:.1f}% | {task.speed_str}",
                "completed": f"✅ Завершено ({task.output_path})",
                "error": f"❌ Ошибка: {task.error_message}",
            }.get(task.status, task.status)

            item = QListWidgetItem(f"[{task.media_type.upper()}]  {task.title}\n{status_text}")
            self.queue_list_widget.addItem(item)

    def _process_queue_batch(self):
        tasks = [t for t in self.queue_manager.get_tasks() if t.status == "pending"]
        if not tasks:
            QMessageBox.information(self, "Очередь", "Нет ожидающих задач для скачивания.")
            return

        self.btn_start_queue.setEnabled(False)
        self._current_queue_task = tasks[0]
        self._current_queue_task.status = "downloading"
        self._render_queue_list()

        opts = self._current_queue_task.options
        self.current_queue_worker = DownloadWorker(self.downloader, self.spotify_downloader, opts)
        self.current_queue_worker.sig_progress.connect(self._on_queue_task_progress)
        self.current_queue_worker.sig_finished.connect(self._on_queue_task_finished)
        self.current_queue_worker.sig_error.connect(self._on_queue_task_error)

        if hasattr(self, "downloads_view"):
            self.downloads_view.add_download(
                self.current_queue_worker,
                opts,
                title=self._current_queue_task.title,
                format_str=f"Очередь: {self._current_queue_task.media_type.upper()}",
            )

        self.current_queue_worker.start()

    def _on_queue_task_progress(self, p_dict: dict):
        if hasattr(self, "_current_queue_task") and self._current_queue_task:
            self._current_queue_task.progress_percent = p_dict.get("percent", 0.0)
            self._current_queue_task.speed_str = p_dict.get("speed_str", "-- МБ/с")
            self._render_queue_list()

    def _on_queue_task_finished(self, res: dict):
        if hasattr(self, "_current_queue_task") and self._current_queue_task:
            self._current_queue_task.status = "completed"
            self._current_queue_task.output_path = res.get("file_path", "")
        self.btn_start_queue.setEnabled(True)
        self._render_queue_list()
        self._refresh_history_badge()
        self._refresh_queue_badge()
        # Запускаем следующую задачу, если есть
        self._process_queue_batch()

    def _on_queue_task_error(self, err_msg: str):
        if hasattr(self, "_current_queue_task") and self._current_queue_task:
            self._current_queue_task.status = "error"
            self._current_queue_task.error_message = err_msg
        self.btn_start_queue.setEnabled(True)
        self._render_queue_list()

    def _clear_queue(self):
        self.queue_manager.clear()
        self._render_queue_list()
        self._refresh_queue_badge()

    # -------------------------------------------------------------------------
    # СТРАНИЦА: ИСТОРИЯ СКАЧИВАНИЙ
    # -------------------------------------------------------------------------

    def _create_history_page(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self.history_header_lbl = QLabel("История загрузок")
        self.history_header_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")

        btn_clean_missing = QPushButton("🧹 Проверить файлы")
        btn_clean_missing.clicked.connect(self._clean_missing_history)

        btn_clear_hist = QPushButton("🗑️ Очистить всё")
        btn_clear_hist.clicked.connect(self._clear_all_history)

        top_row.addWidget(self.history_header_lbl)
        top_row.addStretch()
        top_row.addWidget(btn_clean_missing)
        top_row.addWidget(btn_clear_hist)
        layout.addLayout(top_row)

        self.history_list_widget = QListWidget()
        self.history_list_widget.itemDoubleClicked.connect(self._on_history_double_clicked)
        layout.addWidget(self.history_list_widget)
        return widget

    def _render_history_list(self):
        self.history_list_widget.clear()
        hist = load_history()
        self.history_header_lbl.setText(f"История загрузок ({len(hist)})")

        if not hist:
            item = QListWidgetItem("История пуста. Здесь будут отображаться все скачанные файлы.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history_list_widget.addItem(item)
            return

        for entry in hist:
            f_path = entry.get("file_path", "")
            exists_mark = "✅" if (f_path and os.path.exists(f_path)) else "⚠️ (Файл перемещен или удален)"
            txt = f"{entry.get('title', 'Без названия')}  [{entry.get('format_type', '')}]  •  {entry.get('file_size_str', '')}\n📁 {f_path}  {exists_mark}"
            item = QListWidgetItem(txt)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.history_list_widget.addItem(item)

    def _on_history_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        f_path = data.get("file_path", "")
        if f_path and os.path.exists(f_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(f_path))
        else:
            QMessageBox.warning(self, "Файл не найден", f"Файл не найден по пути:\n{f_path}")

    def _clean_missing_history(self):
        clean_missing_history_entries()
        self._render_history_list()
        self._refresh_history_badge()
        QMessageBox.information(self, "История", "Удалены записи о несуществующих файлах.")

    def _clear_all_history(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Подтверждение")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setText("Вы уверены, что хотите полностью очистить историю?")
        btn_yes = msg.addButton("Да", QMessageBox.ButtonRole.YesRole)
        btn_no = msg.addButton("Нет", QMessageBox.ButtonRole.NoRole)
        msg.setDefaultButton(btn_no)
        msg.exec()
        if msg.clickedButton() == btn_yes:
            clear_history()
            self._render_history_list()
            self._refresh_history_badge()


# =============================================================================
# ТОЧКА ВХОДА ДЛЯ ЗАПУСКА
# =============================================================================

def setup_safe_exception_handling():
    """
    Глобальный перехватчик необработанных исключений и сообщений Qt.
    Предотвращает внезапное падение процесса с кодом 0xC0000409 (qFatal)
    и выводит диагностическую информацию в консоль.
    """
    def qt_message_handler(mode, context, message):
        if any(w in message for w in ("Unknown property", "QFont", "QWindowsWindow")):
            return
        if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
            print(f"[Qt {mode.name}] {message}", file=sys.stderr, flush=True)

    def global_excepthook(exc_type, exc_val, exc_tb):
        err = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        print(f"[Unhandled Exception]\n{err}", file=sys.stderr, flush=True)

    qInstallMessageHandler(qt_message_handler)
    sys.excepthook = global_excepthook


def run_gui():
    setup_safe_exception_handling()
    app = QApplication(sys.argv)
    app.setApplicationName("Media Downloader Pro")

    # Установка встроенной русской локализации Qt для всех стандартных диалогов и кнопок
    try:
        trans_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for t_name in ("qtbase", "qt"):
            tr = QTranslator(app)
            if tr.load(QLocale("ru_RU"), t_name, "_", trans_path):
                app.installTranslator(tr)
    except Exception:
        pass

    window = MediaDownloaderWindow()
    window.show()
    sys.exit(app.exec())


main = run_gui

if __name__ == "__main__":
    run_gui()
