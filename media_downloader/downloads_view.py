"""
Модуль отдельного раздела активных загрузок (downloads_view.py)
Показывает все медиафайлы, которые скачиваются в данный момент, в реальном времени
с прогресс-баром, скоростью, объемом, таймером и кнопками управления.
"""

import os
import uuid
from typing import Dict, Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QThread
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QMessageBox
)

from media_downloader.utils import format_bytes, format_speed, format_eta


class DownloadCardWidget(QFrame):
    """
    Интерактивная карточка отдельного процесса скачивания.
    """
    sig_status_changed = pyqtSignal()
    sig_removed = pyqtSignal(str)

    def __init__(
        self,
        item_id: str,
        title: str,
        url: str,
        format_str: str,
        save_dir: str,
        worker: Optional[QThread] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.item_id = item_id
        self.media_title = title or "Медиафайл"
        self.url = url or ""
        self.format_str = format_str or "Медиа"
        self.save_dir = save_dir or ""
        self.worker = worker
        self.file_path = ""
        self.status = "downloading"  # downloading, finished, error, cancelled

        self.setObjectName("DownloadItemCard")
        self._init_ui()

        if self.worker is not None:
            self._connect_worker()

    def _init_ui(self):
        self.setStyleSheet("""
            QFrame#DownloadItemCard {
                background-color: #191d27;
                border: 1px solid #283144;
                border-radius: 10px;
            }
            QFrame#DownloadItemCard:hover {
                border-color: #38bdf8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # 1. Верхняя строка: Иконка, Заголовок, Формат и кнопка закрытия
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        icon_char = "🎵" if ("mp3" in self.format_str.lower() or "аудио" in self.format_str.lower() or "музыка" in self.format_str.lower()) else "🎬"
        self.lbl_icon = QLabel(icon_char)
        self.lbl_icon.setStyleSheet("""
            background-color: #202b3e;
            color: #38bdf8;
            border-radius: 8px;
            font-size: 18px;
            padding: 6px;
        """)
        self.lbl_icon.setFixedSize(36, 36)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(2)

        t_display = self.media_title if len(self.media_title) <= 75 else (self.media_title[:75] + "...")
        self.lbl_title = QLabel(t_display)
        self.lbl_title.setToolTip(self.media_title)
        self.lbl_title.setStyleSheet("font-size: 13.5px; font-weight: bold; color: #ffffff;")

        tag_text = f"[{self.format_str}]  {self.url}" if self.url else f"[{self.format_str}]"
        tag_disp = tag_text if len(tag_text) <= 90 else (tag_text[:90] + "...")
        self.lbl_tag = QLabel(tag_disp)
        self.lbl_tag.setStyleSheet("font-size: 11px; color: #94a3b8;")

        meta_col.addWidget(self.lbl_title)
        meta_col.addWidget(self.lbl_tag)

        self.lbl_pct = QLabel("0.0%")
        self.lbl_pct.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedSize(24, 24)
        self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #64748b;
                font-size: 13px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                color: #f87171;
                background-color: #2d1f2d;
            }
        """)
        self.btn_remove.setToolTip("Удалить из списка")
        self.btn_remove.clicked.connect(self._on_remove_clicked)

        top_row.addWidget(self.lbl_icon)
        top_row.addLayout(meta_col, 1)
        top_row.addWidget(self.lbl_pct)
        top_row.addWidget(self.btn_remove)
        layout.addLayout(top_row)

        # 2. Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e2535;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # 3. Нижняя строка метрик и кнопок
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(14)

        self.lbl_status = QLabel("⚡ Подключение...")
        self.lbl_status.setStyleSheet("color: #38bdf8; font-size: 11.5px; font-weight: 500;")

        self.lbl_speed = QLabel("⚡ -- МБ/с")
        self.lbl_speed.setStyleSheet("color: #94a3b8; font-size: 11.5px;")

        self.lbl_size = QLabel("💾 -- / --")
        self.lbl_size.setStyleSheet("color: #c084fc; font-size: 11.5px;")

        self.lbl_eta = QLabel("⏱ ETA: --:--")
        self.lbl_eta.setStyleSheet("color: #fbbf24; font-size: 11.5px;")

        bottom_row.addWidget(self.lbl_status)
        bottom_row.addWidget(self.lbl_speed)
        bottom_row.addWidget(self.lbl_size)
        bottom_row.addWidget(self.lbl_eta)
        bottom_row.addStretch()

        # Кнопки действий
        self.btn_cancel = QPushButton("⏹ Отмена")
        self.btn_cancel.setFixedHeight(28)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #27272a;
                color: #f87171;
                border: 1px solid #3f3f46;
                border-radius: 5px;
                font-size: 11.5px;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #451a1a;
                border-color: #f87171;
            }
        """)
        self.btn_cancel.clicked.connect(self.cancel_download)
        bottom_row.addWidget(self.btn_cancel)

        self.btn_open_file = QPushButton("📂 Открыть")
        self.btn_open_file.setFixedHeight(28)
        self.btn_open_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_file.setVisible(False)
        self.btn_open_file.setStyleSheet("""
            QPushButton {
                background-color: #047857;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                font-size: 11.5px;
                padding: 0 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_open_file.clicked.connect(self._open_file)
        bottom_row.addWidget(self.btn_open_file)

        self.btn_open_dir = QPushButton("📁 В папке")
        self.btn_open_dir.setFixedHeight(28)
        self.btn_open_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_dir.setVisible(False)
        self.btn_open_dir.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #475569;
                border-radius: 5px;
                font-size: 11.5px;
                padding: 0 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        self.btn_open_dir.clicked.connect(self._open_dir)
        bottom_row.addWidget(self.btn_open_dir)

        layout.addLayout(bottom_row)

    def _connect_worker(self):
        if hasattr(self.worker, "sig_progress"):
            self.worker.sig_progress.connect(self.on_progress)
        if hasattr(self.worker, "sig_status"):
            self.worker.sig_status.connect(self.on_status)
        if hasattr(self.worker, "sig_finished"):
            self.worker.sig_finished.connect(self.on_finished)
        if hasattr(self.worker, "sig_error"):
            self.worker.sig_error.connect(self.on_error)

    def on_progress(self, p_data: dict):
        if self.status != "downloading":
            return
        frac = p_data.get("fraction", 0.0)
        pct = p_data.get("percent", frac * 100.0)
        val = int(pct * 10)
        self.progress_bar.setValue(min(max(val, 0), 1000))
        self.lbl_pct.setText(f"{pct:.1f}%")

        spd = p_data.get("speed_str") or format_speed(p_data.get("speed"))
        self.lbl_speed.setText(f"⚡ {spd}")

        dld = p_data.get("downloaded_str") or format_bytes(p_data.get("downloaded_bytes", 0))
        tot = p_data.get("total_str") or format_bytes(p_data.get("total_bytes") or p_data.get("total_bytes_estimate", 0))
        self.lbl_size.setText(f"💾 {dld} / {tot}")

        eta = p_data.get("eta_str") or format_eta(p_data.get("eta"))
        self.lbl_eta.setText(f"⏱ ETA: {eta}")

    def on_status(self, text: str):
        if self.status == "downloading" and text:
            self.lbl_status.setText(f"⚡ {text}")

    def on_finished(self, res: dict):
        self.status = "finished"
        self.progress_bar.setValue(1000)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e2535;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #10b981;
                border-radius: 4px;
            }
        """)
        self.lbl_pct.setText("100%")
        self.lbl_pct.setStyleSheet("font-size: 14px; font-weight: bold; color: #34d399;")
        self.lbl_status.setText("✓ Загрузка успешно завершена")
        self.lbl_status.setStyleSheet("color: #34d399; font-size: 11.5px; font-weight: bold;")
        self.lbl_eta.setText("⏱ Завершено")

        if isinstance(res, dict):
            self.file_path = res.get("file_path", "")
            if res.get("title") and self.media_title == "Медиафайл":
                self.media_title = res.get("title")
                self.lbl_title.setText(self.media_title[:75])

        self.btn_cancel.setVisible(False)
        self.btn_open_file.setVisible(True)
        self.btn_open_dir.setVisible(True)
        self.sig_status_changed.emit()

    def on_error(self, err_msg: str):
        self.status = "error"
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e2535;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #ef4444;
                border-radius: 4px;
            }
        """)
        self.lbl_pct.setText("Ошибка")
        self.lbl_pct.setStyleSheet("font-size: 13px; font-weight: bold; color: #f87171;")
        short_err = str(err_msg).strip().splitlines()[-1] if err_msg else "Ошибка"
        self.lbl_status.setText(f"❌ {short_err[:45]}")
        self.lbl_status.setStyleSheet("color: #f87171; font-size: 11.5px;")

        self.btn_cancel.setVisible(False)
        self.sig_status_changed.emit()

    def cancel_download(self):
        if self.status == "downloading":
            self.status = "cancelled"
            if self.worker and self.worker.isRunning():
                try:
                    self.worker.terminate()
                except Exception:
                    pass
            self.lbl_pct.setText("Отменено")
            self.lbl_pct.setStyleSheet("font-size: 13px; font-weight: bold; color: #94a3b8;")
            self.lbl_status.setText("⏹ Скачивание отменено пользователем")
            self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11.5px;")
            self.btn_cancel.setVisible(False)
            self.sig_status_changed.emit()

    def _open_file(self):
        if self.file_path and os.path.exists(self.file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.file_path))
        else:
            self._open_dir()

    def _open_dir(self):
        target = self.save_dir
        if self.file_path and os.path.exists(self.file_path):
            target = os.path.dirname(self.file_path)
        if target and os.path.exists(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _on_remove_clicked(self):
        if self.status == "downloading":
            msg = QMessageBox(self)
            msg.setWindowTitle("Подтверждение")
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setText("Скачивание ещё выполняется. Отменить и удалить из списка?")
            btn_yes = msg.addButton("Да", QMessageBox.ButtonRole.YesRole)
            btn_no = msg.addButton("Нет", QMessageBox.ButtonRole.NoRole)
            msg.setDefaultButton(btn_no)
            msg.exec()
            if msg.clickedButton() != btn_yes:
                return
            self.cancel_download()
        self.sig_removed.emit(self.item_id)


class DownloadsView(QWidget):
    """
    Полноценный раздел интерфейса «Загрузки» для мониторинга всех активных
    и завершенных скачиваний.
    """
    sig_active_count_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.download_cards: Dict[str, DownloadCardWidget] = {}
        self.current_filter = "all"  # "all", "active", "finished"
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Шапка раздела
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.lbl_header = QLabel("⚡ Активные загрузки")
        self.lbl_header.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        self.lbl_sub = QLabel("Мониторинг всех процессов скачивания в реальном времени")
        self.lbl_sub.setStyleSheet("font-size: 11.5px; color: #94a3b8;")
        title_col.addWidget(self.lbl_header)
        title_col.addWidget(self.lbl_sub)

        header_row.addLayout(title_col, 1)

        # Фильтры
        self.btn_filter_all = QPushButton("Все (0)")
        self.btn_filter_all.setFixedHeight(32)
        self.btn_filter_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filter_all.setStyleSheet("background-color: #202b3e; color: #38bdf8; border: 1px solid #38bdf8; border-radius: 6px; padding: 0 12px; font-weight: bold;")
        self.btn_filter_all.clicked.connect(lambda: self._set_filter("all"))

        self.btn_filter_active = QPushButton("Скачиваются (0)")
        self.btn_filter_active.setFixedHeight(32)
        self.btn_filter_active.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filter_active.setStyleSheet("background-color: #181c26; color: #94a3b8; border: 1px solid #283144; border-radius: 6px; padding: 0 12px;")
        self.btn_filter_active.clicked.connect(lambda: self._set_filter("active"))

        self.btn_filter_finished = QPushButton("Завершенные (0)")
        self.btn_filter_finished.setFixedHeight(32)
        self.btn_filter_finished.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filter_finished.setStyleSheet("background-color: #181c26; color: #94a3b8; border: 1px solid #283144; border-radius: 6px; padding: 0 12px;")
        self.btn_filter_finished.clicked.connect(lambda: self._set_filter("finished"))

        self.btn_clear_finished = QPushButton("🗑️ Очистить завершенные")
        self.btn_clear_finished.setFixedHeight(32)
        self.btn_clear_finished.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_finished.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11.5px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        self.btn_clear_finished.clicked.connect(self._clear_finished)

        header_row.addWidget(self.btn_filter_all)
        header_row.addWidget(self.btn_filter_active)
        header_row.addWidget(self.btn_filter_finished)
        header_row.addWidget(self.btn_clear_finished)

        layout.addLayout(header_row)

        # 2. Область карточек загрузок
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background-color: transparent;")

        self.container_widget = QWidget()
        self.container_layout = QVBoxLayout(self.container_widget)
        self.container_layout.setContentsMargins(0, 4, 0, 10)
        self.container_layout.setSpacing(12)

        # Плейсхолдер пустого списка
        self.empty_card = QFrame()
        self.empty_card.setObjectName("EmptyCard")
        self.empty_card.setStyleSheet("""
            QFrame#EmptyCard {
                background-color: #181c26;
                border: 1px dashed #283144;
                border-radius: 12px;
            }
        """)
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 32, 24, 32)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(10)

        lbl_emp_icon = QLabel("⬇️")
        lbl_emp_icon.setStyleSheet("font-size: 38px; margin-bottom: 2px;")
        lbl_emp_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_emp_title = QLabel("Нет активных загрузок")
        lbl_emp_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        lbl_emp_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_emp_desc = QLabel("Здесь отобразится подробный прогресс, скорость и время\nпри запуске скачивания любого видео или трека.")
        lbl_emp_desc.setStyleSheet("font-size: 12.5px; color: #64748b;")
        lbl_emp_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(lbl_emp_icon)
        empty_layout.addWidget(lbl_emp_title)
        empty_layout.addWidget(lbl_emp_desc)

        self.container_layout.addWidget(self.empty_card)
        self.container_layout.addStretch()

        self.scroll_area.setWidget(self.container_widget)
        layout.addWidget(self.scroll_area, 1)

    def add_download(
        self,
        worker: QThread,
        options: Dict[str, Any],
        title: str = "",
        format_str: str = "",
    ) -> DownloadCardWidget:
        """
        Регистрирует новую загрузку и добавляет карточку в список.
        """
        item_id = uuid.uuid4().hex[:8]
        url = options.get("url", "")
        save_dir = options.get("save_dir", "")

        if not format_str:
            if options.get("mode") == "audio":
                format_str = f"Аудио {options.get('audio_format', 'mp3').upper()}"
            else:
                res = options.get("resolution", "HD")
                cont = options.get("container", "mp4").upper()
                format_str = f"Видео {res} ({cont})"

        card = DownloadCardWidget(
            item_id=item_id,
            title=title or "Медиафайл",
            url=url,
            format_str=format_str,
            save_dir=save_dir,
            worker=worker,
            parent=self.container_widget,
        )
        card.sig_status_changed.connect(self._on_item_status_changed)
        card.sig_removed.connect(self._remove_item)

        self.download_cards[item_id] = card

        # Вставляем перед растяжкой вверху списка (новые загрузки первыми)
        self.container_layout.insertWidget(0, card)

        self.empty_card.setVisible(False)
        self._update_filter_counts()
        self._apply_filter()
        self.sig_active_count_changed.emit(self.get_active_count())
        return card

    def get_active_count(self) -> int:
        return sum(1 for c in self.download_cards.values() if c.status == "downloading")

    def _on_item_status_changed(self):
        self._update_filter_counts()
        self._apply_filter()
        self.sig_active_count_changed.emit(self.get_active_count())

    def _remove_item(self, item_id: str):
        if item_id in self.download_cards:
            card = self.download_cards.pop(item_id)
            self.container_layout.removeWidget(card)
            card.deleteLater()
            self._update_filter_counts()
            self._apply_filter()
            self.sig_active_count_changed.emit(self.get_active_count())

    def _clear_finished(self):
        to_del = [item_id for item_id, c in self.download_cards.items() if c.status in ("finished", "error", "cancelled")]
        for item_id in to_del:
            self._remove_item(item_id)

    def _set_filter(self, filter_name: str):
        self.current_filter = filter_name
        active_style = "background-color: #202b3e; color: #38bdf8; border: 1px solid #38bdf8; border-radius: 6px; padding: 0 12px; font-weight: bold;"
        norm_style = "background-color: #181c26; color: #94a3b8; border: 1px solid #283144; border-radius: 6px; padding: 0 12px;"

        self.btn_filter_all.setStyleSheet(active_style if filter_name == "all" else norm_style)
        self.btn_filter_active.setStyleSheet(active_style if filter_name == "active" else norm_style)
        self.btn_filter_finished.setStyleSheet(active_style if filter_name == "finished" else norm_style)

        self._apply_filter()

    def _apply_filter(self):
        visible_count = 0
        for card in self.download_cards.values():
            should_show = False
            if self.current_filter == "all":
                should_show = True
            elif self.current_filter == "active":
                should_show = (card.status == "downloading")
            elif self.current_filter == "finished":
                should_show = (card.status in ("finished", "error", "cancelled"))

            card.setVisible(should_show)
            if should_show:
                visible_count += 1

        self.empty_card.setVisible(visible_count == 0)

    def _update_filter_counts(self):
        total = len(self.download_cards)
        active = sum(1 for c in self.download_cards.values() if c.status == "downloading")
        finished = sum(1 for c in self.download_cards.values() if c.status in ("finished", "error", "cancelled"))

        self.btn_filter_all.setText(f"Все ({total})")
        self.btn_filter_active.setText(f"Скачиваются ({active})")
        self.btn_filter_finished.setText(f"Завершенные ({finished})")
        self.lbl_header.setText(f"⚡ Активные загрузки ({active})" if active > 0 else "⚡ Активные загрузки")

    def refresh_view(self):
        self._update_filter_counts()
        self._apply_filter()
