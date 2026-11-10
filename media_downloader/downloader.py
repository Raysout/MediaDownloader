"""
Фасад обратной совместимости для модуля загрузки медиа (downloader.py).
Реэкспортирует MediaDownloader из media_downloader.core.downloader.
"""

from media_downloader.core.downloader import MediaDownloader

__all__ = ["MediaDownloader"]
