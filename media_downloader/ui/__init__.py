"""
Пакет пользовательского интерфейса PyQt6 (media_downloader.ui)
"""

from media_downloader.ui.styles import build_app_stylesheet
from media_downloader.ui.widgets import SegmentedButton
from media_downloader.ui.workers import (
    ThumbnailWorker,
    AnalyzeWorker,
    DownloadWorker,
)
from media_downloader.ui.base_view import (
    DetachedServiceWindow,
    BaseDownloadView,
)
from media_downloader.ui.video_views import (
    YouTubeSingleVideoView,
    YouTubePlaylistView,
    TikTokVideoView,
    OtherVideoView,
    VideoHubView,
)
from media_downloader.ui.music_views import (
    SpotifyTrackView,
    SpotifyPlaylistView,
    SoundCloudView,
    YTMusicView,
    OtherMusicView,
    MusicHubView,
)
from media_downloader.ui.main_window import (
    MediaDownloaderWindow,
    setup_safe_exception_handling,
    run_gui,
    main,
)

__all__ = [
    "build_app_stylesheet",
    "SegmentedButton",
    "ThumbnailWorker",
    "AnalyzeWorker",
    "DownloadWorker",
    "DetachedServiceWindow",
    "BaseDownloadView",
    "YouTubeSingleVideoView",
    "YouTubePlaylistView",
    "TikTokVideoView",
    "OtherVideoView",
    "VideoHubView",
    "SpotifyTrackView",
    "SpotifyPlaylistView",
    "SoundCloudView",
    "YTMusicView",
    "OtherMusicView",
    "MusicHubView",
    "MediaDownloaderWindow",
    "setup_safe_exception_handling",
    "run_gui",
    "main",
]
