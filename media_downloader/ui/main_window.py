"""
Главное окно приложения (main_window.py)
Содержит MediaDownloaderWindow, боковую панель, вкладки очередей и истории,
а также точку инициализации GUI.
"""

import os
import sys
import traceback
from typing import Dict, Any, Optional

from PyQt6.QtCore import (
    Qt, QTimer, QUrl,
    qInstallMessageHandler, QtMsgType, QTranslator, QLibraryInfo, QLocale
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox,
    QStackedWidget, QListWidget, QListWidgetItem, QFrame, QMessageBox
)

from media_downloader.core import (
    MediaDownloader,
    SpotifyDownloader,
    DownloadQueueManager,
    load_history,
    clear_history,
    clean_missing_history_entries,
)
from media_downloader.ui.theme_manager import PALETTES
from media_downloader.ui.downloads_view import DownloadsView
from media_downloader.ui.styles import build_app_stylesheet
from media_downloader.ui.base_view import BaseDownloadView, DetachedServiceWindow
from media_downloader.ui.video_views import VideoHubView
from media_downloader.ui.music_views import MusicHubView
from media_downloader.ui.workers import DownloadWorker
from media_downloader.utils import (
    is_valid_url, get_system_clipboard_text, check_ffmpeg_installed
)


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
