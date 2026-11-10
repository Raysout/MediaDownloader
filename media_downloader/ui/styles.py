"""
Модуль стилизации интерфейса (styles.py)
Содержит генератор QSS стилей под Material 3.
"""


def build_app_stylesheet(primary_hex: str, accent_hex: str, hover_hex: str) -> str:
    """
    Генерирует полную таблицу QSS-стилей приложения с поддержкой динамических акцентных цветов.
    """
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
