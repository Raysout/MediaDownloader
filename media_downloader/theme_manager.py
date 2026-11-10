"""
Модуль управления темами оформления и цветовыми палитрами (theme_manager.py)
Обеспечивает гармоничные цветовые схемы для графического интерфейса.
"""

from typing import Dict, Tuple, Any

PALETTES: Dict[str, Dict[str, Any]] = {
    "Ocean Blue": {
        "name": "Ocean Blue",
        "primary": "#1F6AA5",
        "hover": "#144870",
        "accent": "#3B8ED0",
        "gradient": ("#1F6AA5", "#0E3854"),
        "light_gradient": ("#3B8ED0", "#1F6AA5"),
        "badge_bg": ("#D4E6F1", "#1B2631"),
        "badge_text": ("#154360", "#85C1E9"),
    },
    "Emerald Green": {
        "name": "Emerald Green",
        "primary": "#27AE60",
        "hover": "#1E8449",
        "accent": "#2ECC71",
        "gradient": ("#27AE60", "#145A32"),
        "light_gradient": ("#2ECC71", "#27AE60"),
        "badge_bg": ("#D5F5E3", "#145A32"),
        "badge_text": ("#196F3D", "#A9DFBF"),
    },
    "Cyberpunk Purple": {
        "name": "Cyberpunk Purple",
        "primary": "#8E44AD",
        "hover": "#6C3483",
        "accent": "#A569BD",
        "gradient": ("#8E44AD", "#4A235A"),
        "light_gradient": ("#A569BD", "#8E44AD"),
        "badge_bg": ("#EBDEF0", "#2C1B33"),
        "badge_text": ("#5B2C6F", "#D7BDE2"),
    },
    "Sunset Orange": {
        "name": "Sunset Orange",
        "primary": "#E67E22",
        "hover": "#B95E13",
        "accent": "#F39C12",
        "gradient": ("#E67E22", "#935116"),
        "light_gradient": ("#F39C12", "#E67E22"),
        "badge_bg": ("#FDEBD0", "#2C1B0F"),
        "badge_text": ("#7E5109", "#F8C471"),
    },
    "Dark Graphite": {
        "name": "Dark Graphite",
        "primary": "#34495E",
        "hover": "#2C3E50",
        "accent": "#5D6D7E",
        "gradient": ("#34495E", "#1B2631"),
        "light_gradient": ("#5D6D7E", "#34495E"),
        "badge_bg": ("#EAECEE", "#1C2833"),
        "badge_text": ("#283747", "#ABB2B9"),
    },
}


def hex_to_rgb(hex_code: str) -> Tuple[int, int, int]:
    """
    Преобразует hex-код цвета (#RRGGBB) в кортеж RGB.
    """
    clean_hex = hex_code.lstrip("#")
    return int(clean_hex[0:2], 16), int(clean_hex[2:4], 16), int(clean_hex[4:6], 16)
