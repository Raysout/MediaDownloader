"""
Фасад обратной совместимости для раздела активных загрузок (downloads_view.py).
Реэкспортирует классы из медиа-пакета media_downloader.ui.downloads_view.
"""

from media_downloader.ui.downloads_view import (
    DownloadCardWidget,
    DownloadsView,
)

__all__ = [
    "DownloadCardWidget",
    "DownloadsView",
]
