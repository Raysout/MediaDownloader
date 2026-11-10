"""
Функции форматирования величин (formatters.py)
Форматирование байтов, скорости передачи данных и временных интервалов.
"""

from typing import Optional


def format_bytes(bytes_count: Optional[float | int]) -> str:
    """
    Форматирует размер в байтах в человекочитаемый вид (Б, КБ, МБ, ГБ).

    :param bytes_count: Число байтов.
    :return: Строка с числом и единицей измерения.
    """
    if bytes_count is None or bytes_count < 0:
        return "0 Б"

    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    size = float(bytes_count)
    unit_index = 0

    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def format_speed(bytes_per_second: Optional[float | int]) -> str:
    """
    Форматирует скорость скачивания (Б/с -> КБ/с, МБ/с).

    :param bytes_per_second: Скорость в байтах в секунду.
    :return: Строка вида "5.24 МБ/с".
    """
    if bytes_per_second is None or bytes_per_second <= 0:
        return "-- МБ/с"
    return f"{format_bytes(bytes_per_second)}/с"


def format_duration(seconds: Optional[float | int]) -> str:
    """
    Преобразует длительность в секундах в формат ЧЧ:ММ:СС или ММ:СС.

    :param seconds: Длительность в секундах.
    :return: Форматированная строка времени.
    """
    if seconds is None or seconds < 0:
        return "Неизвестно"

    total_sec = int(seconds)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_eta(seconds: Optional[float | int]) -> str:
    """
    Преобразует оставшееся время скачивания (ETA) в строку.

    :param seconds: Количество секунд до завершения.
    :return: Строка времени.
    """
    if seconds is None or seconds < 0:
        return "--:--"
    return format_duration(seconds)


def parse_time_to_seconds(time_str: Optional[str]) -> Optional[float]:
    """
    Преобразует строку времени вида 'ЧЧ:ММ:СС', 'ММ:СС' или 'СС' в секунды.

    :param time_str: Строка с таймкодом (например, '01:30' или '01:15:20').
    :return: Число секунд или None, если строка пуста или некорректна.
    """
    if not time_str or not isinstance(time_str, str):
        return None

    cleaned = time_str.strip()
    if not cleaned:
        return None

    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60.0 + s
        elif len(parts) == 1:
            return float(parts[0])
    except (ValueError, TypeError):
        return None

    return None
