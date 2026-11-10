"""
Пакет базовой бизнес-логики (media_downloader.core)
"""

from media_downloader.core.downloader import MediaDownloader
from media_downloader.core.spotify import (
    SpotifyDownloader,
    parse_spotify_url,
    is_spotify_url,
)
from media_downloader.core.queue import (
    DownloadTask,
    DownloadQueueManager,
)
from media_downloader.core.history import (
    load_history,
    save_history,
    add_history_entry,
    clear_history,
    delete_history_entry,
    clean_missing_history_entries,
)

__all__ = [
    "MediaDownloader",
    "SpotifyDownloader",
    "parse_spotify_url",
    "is_spotify_url",
    "DownloadTask",
    "DownloadQueueManager",
    "load_history",
    "save_history",
    "add_history_entry",
    "clear_history",
    "delete_history_entry",
    "clean_missing_history_entries",
]
