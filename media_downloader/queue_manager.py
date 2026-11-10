"""
Фасад обратной совместимости для диспетчера очереди (queue_manager.py).
Реэкспортирует классы из media_downloader.core.queue.
"""

from media_downloader.core.queue import (
    DownloadTask,
    DownloadQueueManager,
)

__all__ = [
    "DownloadTask",
    "DownloadQueueManager",
]
