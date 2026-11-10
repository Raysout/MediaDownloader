"""
Модуль графического интерфейса на PyQt6 (qt_gui.py)
Служит фасадом обратной совместимости и реэкспортирует компоненты из пакета media_downloader.ui.
"""

from media_downloader.theme_manager import PALETTES
from media_downloader.ui import (
    build_app_stylesheet,
    SegmentedButton,
    ThumbnailWorker,
    AnalyzeWorker,
    DownloadWorker,
    DetachedServiceWindow,
    BaseDownloadView,
    YouTubeSingleVideoView,
    YouTubePlaylistView,
    TikTokVideoView,
    OtherVideoView,
    VideoHubView,
    SpotifyTrackView,
    SpotifyPlaylistView,
    SoundCloudView,
    YTMusicView,
    OtherMusicView,
    MusicHubView,
    MediaDownloaderWindow,
    setup_safe_exception_handling,
    run_gui,
    main,
)

if __name__ == "__main__":
    run_gui()
