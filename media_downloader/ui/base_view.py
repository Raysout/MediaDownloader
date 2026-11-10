"""
Базовый класс экрана загрузки (base_view.py)
Содержит BaseDownloadView и окно открепления DetachedServiceWindow.
"""

import os
from typing import Optional, Callable, Any, Dict

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import (
    QPixmap, QPainter, QPainterPath, QDesktopServices
)
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar,
    QFrame, QScrollArea, QFileDialog, QMessageBox, QApplication
)

from media_downloader.core import (
    MediaDownloader,
    SpotifyDownloader,
    DownloadQueueManager,
)
from media_downloader.ui.workers import (
    AnalyzeWorker, DownloadWorker, ThumbnailWorker
)
from media_downloader.utils import (
    get_default_download_dir, get_system_clipboard_text
)


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
