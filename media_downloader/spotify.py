"""
Фасад обратной совместимости для модуля Spotify (spotify.py).
Реэкспортирует классы и функции из media_downloader.core.spotify.
"""

from media_downloader.core.spotify import (
    SpotifyDownloader,
    parse_spotify_url,
    is_spotify_url,
)

__all__ = [
    "SpotifyDownloader",
    "parse_spotify_url",
    "is_spotify_url",
]
