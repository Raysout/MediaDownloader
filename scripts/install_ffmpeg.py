"""
Скрипт автоматической загрузки и установки портативного FFmpeg для Windows.
Скачивает официальную сборку с gyan.dev и извлекает ffmpeg.exe и ffprobe.exe в media_downloader/bin.
"""

import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download_progress(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100.0, downloaded * 100.0 / total_size)
        mb_downloaded = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        bar_len = 30
        filled_len = int(bar_len * percent / 100)
        bar = "=" * filled_len + "-" * (bar_len - filled_len)
        sys.stdout.write(f"\r[{bar}] {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} МБ)")
        sys.stdout.flush()


def install_ffmpeg():
    # scripts/install_ffmpeg.py -> parent.parent is project root
    project_root = Path(__file__).resolve().parent.parent
    target_bin = project_root / "media_downloader" / "bin"
    target_bin.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = target_bin / "ffmpeg.exe"
    ffprobe_exe = target_bin / "ffprobe.exe"

    if ffmpeg_exe.exists():
        print(f"FFmpeg уже установлен в: {ffmpeg_exe}")
        return

    temp_zip = project_root / "ffmpeg_temp.zip"
    print("Загрузка официального архива FFmpeg (Gyan.dev)...")
    print(f"URL: {FFMPEG_URL}")

    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(FFMPEG_URL, headers=headers)

    try:
        with urllib.request.urlopen(req) as response, open(temp_zip, "wb") as out_file:
            total_size = int(response.info().get("Content-Length", -1))
            block_size = 1024 * 1024  # 1 MB blocks
            downloaded = 0
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                out_file.write(buffer)
                downloaded += len(buffer)
                if total_size > 0:
                    percent = min(100.0, downloaded * 100.0 / total_size)
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    sys.stdout.write(f"\rСкачивание: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} МБ)")
                    sys.stdout.flush()

        print("\nРаспаковка исполняемых файлов (ffmpeg.exe, ffprobe.exe)...")
        with zipfile.ZipFile(temp_zip, "r") as zip_ref:
            for member in zip_ref.namelist():
                filename = Path(member).name
                if filename in ("ffmpeg.exe", "ffprobe.exe"):
                    data = zip_ref.read(member)
                    target = target_bin / filename
                    with open(target, "wb") as f_out:
                        f_out.write(data)
                    print(f" -> Извлечен: {filename}")

        print(f"\n[Успех] FFmpeg успешно установлен в папку: {target_bin}")
        print("Теперь Media Downloader готов к полноценной работе со всеми форматами и 4K видео!")

    except Exception as e:
        print(f"\n[Ошибка при установке]: {e}")
    finally:
        if temp_zip.exists():
            temp_zip.unlink()


if __name__ == "__main__":
    install_ffmpeg()
