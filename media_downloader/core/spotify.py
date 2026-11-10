"""
Модуль интеграции со Spotify (spotify.py)

Реализует технологию Spotify Metadata Matching:
1. Извлечение точных метаданных (название, исполнители, альбом, HD-обложка, длительность)
   для треков, альбомов и плейлистов через открытые endpoint'ы Spotify Embed и oEmbed.
2. Поиск официального аудиопотока наилучшего качества через YouTube / YouTube Music.
3. Скачивание аудио в формате MP3 (320 kbps), FLAC, M4A.
4. Вшивание официальной Spotify HD-обложки и ID3-тегов (исполнитель, альбом, трек) с помощью mutagen.
"""

import json
import os
import re
import urllib.request
from typing import Dict, Any, Optional, Tuple, Callable

from media_downloader.core.downloader import MediaDownloader
from media_downloader.utils import (
    format_duration,
    sanitize_filename,
)


def parse_spotify_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Определяет тип объекта Spotify (track, album, playlist) и его идентификатор.

    :param url: Ссылка на Spotify.
    :return: Кортеж (тип, id) или (None, None).
    """
    if not url or not isinstance(url, str):
        return None, None

    cleaned = url.strip()
    match = re.search(r"open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([a-zA-Z0-9]+)", cleaned)
    if match:
        return match.group(1).lower(), match.group(2)
    return None, None


def is_spotify_url(url: str) -> bool:
    """
    Проверяет, является ли ссылка адресом трека, альбома или плейлиста Spotify.
    """
    item_type, _ = parse_spotify_url(url)
    return item_type is not None


class SpotifyDownloader:
    """
    Класс для парсинга и скачивания медиа со Spotify.
    """

    def __init__(self, media_downloader: Optional[MediaDownloader] = None):
        self.downloader = media_downloader or MediaDownloader()

    def extract_info(self, url: str) -> Dict[str, Any]:
        """
        Извлекает подробные метаданные по ссылке Spotify (трек, альбом или плейлист).
        """
        item_type, item_id = parse_spotify_url(url)
        if not item_type or not item_id:
            raise ValueError("Некорректная ссылка на Spotify. Поддерживаются треки, альбомы и плейлисты.")

        embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}"
        req = urllib.request.Request(
            embed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8")
        except Exception as exc:
            # Fallback к oEmbed
            return self._extract_oembed_fallback(url, item_type)

        entity = None
        for tag in re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
            if "props" in tag and "pageProps" in tag:
                try:
                    data = json.loads(tag)
                    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    if entity:
                        break
                except Exception:
                    continue

        if not entity:
            return self._extract_oembed_fallback(url, item_type)

        if item_type == "track":
            name = entity.get("name") or "Неизвестный трек"
            artists_list = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
            artists_str = ", ".join(artists_list) if artists_list else "Неизвестный исполнитель"
            album_name = entity.get("album", {}).get("name") or ""

            duration_ms = entity.get("duration") or 0
            duration_sec = duration_ms / 1000.0 if duration_ms else None
            duration_str = format_duration(duration_sec)

            images = entity.get("visualIdentity", {}).get("image", [])
            cover_url = images[0].get("url") if images else None

            search_query = f"{artists_str} - {name}"

            return {
                "type": "track",
                "url": url,
                "title": name,
                "artists": artists_str,
                "album": album_name,
                "duration_sec": duration_sec,
                "duration_str": duration_str,
                "thumbnail_url": cover_url,
                "search_query": search_query,
                "track_count": 1,
                "tracks": [
                    {
                        "title": name,
                        "artist": artists_str,
                        "album": album_name,
                        "duration_str": duration_str,
                        "search_query": search_query,
                        "thumbnail_url": cover_url,
                    }
                ],
            }

        else:
            # album или playlist
            collection_name = entity.get("name") or ("Альбом Spotify" if item_type == "album" else "Плейлист Spotify")
            images = entity.get("visualIdentity", {}).get("image", [])
            cover_url = images[0].get("url") if images else None

            author = entity.get("subtitle") or "Spotify"

            track_items = []
            for t in entity.get("trackList", []):
                t_title = t.get("title") or "Трек"
                t_artist = t.get("subtitle") or author
                t_dur_ms = t.get("duration") or 0
                t_dur_str = format_duration(t_dur_ms / 1000.0) if t_dur_ms else "--:--"

                search_q = f"{t_artist} - {t_title}"
                track_items.append({
                    "title": t_title,
                    "artist": t_artist,
                    "album": collection_name if item_type == "album" else "",
                    "duration_str": t_dur_str,
                    "search_query": search_q,
                    "thumbnail_url": cover_url,
                })

            return {
                "type": item_type,
                "url": url,
                "title": collection_name,
                "artists": author,
                "album": collection_name if item_type == "album" else "",
                "duration_str": f"{len(track_items)} треков",
                "thumbnail_url": cover_url,
                "search_query": collection_name,
                "track_count": len(track_items),
                "tracks": track_items,
            }

    def _extract_oembed_fallback(self, url: str, item_type: str) -> Dict[str, Any]:
        """
        Запасной метод извлечения базовых метаданных через Spotify oEmbed API.
        """
        oembed_url = f"https://open.spotify.com/oembed?url={urllib.request.quote(url)}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_title = data.get("title", "Медиа Spotify")
        thumbnail_url = data.get("thumbnail_url")

        artist = "Spotify"
        title = raw_title
        if " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()

        search_query = f"{artist} - {title}" if artist != "Spotify" else title

        return {
            "type": item_type,
            "url": url,
            "title": title,
            "artists": artist,
            "album": "",
            "duration_str": "--:--",
            "thumbnail_url": thumbnail_url,
            "search_query": search_query,
            "track_count": 1,
            "tracks": [
                {
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "duration_str": "--:--",
                    "search_query": search_query,
                    "thumbnail_url": thumbnail_url,
                }
            ],
        }

    def download_track(
        self,
        track_data: Dict[str, Any],
        output_dir: str,
        audio_format: str = "mp3",
        bitrate: str = "320",
        embed_thumbnail: bool = True,
        normalize_volume: bool = False,
        ratelimit: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Скачивает один трек Spotify через подбор в YouTube Music.
        Вшивает обложку Spotify и ID3-теги.
        """
        os.makedirs(output_dir, exist_ok=True)
        search_query = track_data.get("search_query") or f"{track_data.get('artist', '')} - {track_data.get('title', '')}"
        yt_query = f"ytsearch1:{search_query}"

        if status_callback:
            status_callback(f"Поиск трека: {search_query}...")

        # Скачивание аудио через базовый MediaDownloader
        result = self.downloader.download_audio(
            url=yt_query,
            output_dir=output_dir,
            audio_format=audio_format,
            bitrate=bitrate,
            embed_thumbnail=False,
            custom_title=track_data.get("title"),
            custom_artist=track_data.get("artist"),
            custom_album=track_data.get("album"),
            normalize_volume=normalize_volume,
            ratelimit=ratelimit,
            progress_callback=progress_callback,
            status_callback=status_callback,
        )

        final_path = result.get("file_path")
        # Вшиваем обложку Spotify, если доступна
        thumb_url = track_data.get("thumbnail_url")
        if embed_thumbnail and thumb_url and final_path and os.path.exists(final_path):
            self._embed_spotify_cover(final_path, thumb_url, audio_format)

        return {
            "status": "success",
            "file_path": final_path,
            "file_size": result.get("file_size", 0),
            "file_size_str": result.get("file_size_str", "0 МБ"),
            "title": track_data.get("title", "Трек"),
            "artist": track_data.get("artist", "Исполнитель"),
            "url": track_data.get("url", ""),
        }

    def download_collection(
        self,
        collection_info: Dict[str, Any],
        output_dir: str,
        audio_format: str = "mp3",
        bitrate: str = "320",
        embed_thumbnail: bool = True,
        normalize_volume: bool = False,
        limit_count: Optional[int] = None,
        ratelimit: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        item_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Скачивает альбом или плейлист Spotify в отдельную папку.
        """
        col_title = collection_info.get("title", "Spotify Collection")
        safe_folder = sanitize_filename(col_title) or "Spotify_Playlist"
        target_dir = os.path.join(output_dir, safe_folder)
        os.makedirs(target_dir, exist_ok=True)

        tracks = collection_info.get("tracks", [])
        if limit_count and limit_count > 0:
            tracks = tracks[:limit_count]

        total_tracks = len(tracks)
        downloaded = 0
        failed = 0

        for idx, t in enumerate(tracks, 1):
            t_title = t.get("title", f"Трек {idx}")
            t_artist = t.get("artist", "")
            if item_callback:
                item_callback(idx, total_tracks, f"{t_artist} - {t_title}")

            if status_callback:
                status_callback(f"Spotify [{idx}/{total_tracks}]: {t_artist} - {t_title}...")

            try:
                self.download_track(
                    track_data=t,
                    output_dir=target_dir,
                    audio_format=audio_format,
                    bitrate=bitrate,
                    embed_thumbnail=embed_thumbnail,
                    normalize_volume=normalize_volume,
                    ratelimit=ratelimit,
                    progress_callback=progress_callback,
                    status_callback=None,
                )
                downloaded += 1
            except Exception as exc:
                print(f"[!] Ошибка скачивания трека Spotify '{t_title}': {exc}")
                failed += 1

        if status_callback:
            status_callback(f"Загрузка Spotify завершена! Скачано: {downloaded}/{total_tracks}")

        return {
            "status": "success",
            "file_path": target_dir,
            "title": col_title,
            "count": downloaded,
            "total": total_tracks,
            "failed": failed,
        }

    def _embed_spotify_cover(self, audio_file_path: str, cover_url: str, audio_format: str):
        """
        Скачивает оригинальную обложку Spotify и вшивает в MP3/FLAC/M4A с помощью mutagen.
        """
        try:
            req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as res:
                cover_data = res.read()

            ext = audio_format.lower().strip()
            if ext == "mp3":
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3, APIC, error
                try:
                    audio = MP3(audio_file_path, ID3=ID3)
                    try:
                        audio.add_tags()
                    except error as id3_add_err:
                        _ = id3_add_err
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=3,  # cover front
                            desc="Cover",
                            data=cover_data,
                        )
                    )
                    audio.save(v2_version=3)
                except Exception as id3_err:
                    print(f"[!] Не удалось вшить обложку в MP3: {id3_err}")
            elif ext == "flac":
                from mutagen.flac import FLAC, Picture
                audio = FLAC(audio_file_path)
                image = Picture()
                image.type = 3
                image.mime = "image/jpeg"
                image.desc = "Front Cover"
                image.data = cover_data
                audio.add_picture(image)
                audio.save()
            elif ext in ("m4a", "mp4"):
                from mutagen.mp4 import MP4, MP4Cover
                audio = MP4(audio_file_path)
                audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()
        except Exception as exc:
            print(f"[!] Ошибка сохранения обложки Spotify: {exc}")
