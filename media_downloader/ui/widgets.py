"""
Модуль пользовательских виджетов интерфейса (widgets.py)
Содержит SegmentedButton и вспомогательные компоненты.
"""

from typing import List, Tuple, Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QPushButton, QButtonGroup
)


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
