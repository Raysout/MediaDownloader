"""
Скрипт сборки автономного исполняемого файла (.exe) для Windows с помощью PyInstaller.

Включает:
- Сборку PyQt6 графического интерфейса
- Вшивание бинарников FFmpeg (ffmpeg.exe, ffprobe.exe)
- Отключение консольного окна (--noconsole)
- Создание оптимизированного дистрибутива в папке dist/MediaDownloader
"""

import os
import subprocess
import sys
from pathlib import Path


def build():
    # scripts/build_exe.py -> parent.parent is project root
    project_root = Path(__file__).resolve().parent.parent
    bin_dir = project_root / "media_downloader" / "bin"
    ffmpeg_exe = bin_dir / "ffmpeg.exe"
    ffprobe_exe = bin_dir / "ffprobe.exe"

    if not ffmpeg_exe.exists() or not ffprobe_exe.exists():
        print("[!] FFmpeg не обнаружен в media_downloader/bin.")
        print("    Запустите сначала `python scripts/install_ffmpeg.py` для скачивания.")
        return

    # Проверка наличия PyInstaller
    try:
        import PyInstaller
        print(f"[*] Используется PyInstaller v{PyInstaller.__version__}")
    except ImportError:
        print("[*] Установка PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    main_script = str(project_root / "main.py")

    # Формируем аргументы для PyInstaller
    # Запятая-точка (;) используется в Windows для разделения источника и назначения в --add-binary
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=MediaDownloader",
        "--noconsole",          # Скрывает консольное окно Windows
        "--clean",              # Очищает кэш перед сборкой
        "--onedir",             # Папка со всеми библиотеками (быстрый запуск без распаковки)
        "--collect-all=PyQt6",          # Модули PyQt6 GUI
        "--collect-all=yt_dlp",         # Экстракторы yt-dlp
        "--collect-all=mutagen",        # Поддержка записи ID3 и аудиотегов
        "--collect-all=curl_cffi",     # Обход Cloudflare/TLS-защиты соцсетей
        f"--add-binary={ffmpeg_exe};media_downloader/bin",
        f"--add-binary={ffprobe_exe};media_downloader/bin",
        main_script,
    ]

    # Добавляем иконку, если файл app.ico или icon.ico существует
    icon_path = project_root / "assets" / "icon.ico"
    if icon_path.exists():
        cmd.insert(cmd.index(main_script), f"--icon={icon_path}")

    print("\n[*] Запуск компиляции в .exe...")
    print(" ".join(cmd))
    print("-" * 60)

    try:
        subprocess.check_call(cmd, cwd=str(project_root))
        dist_dir = project_root / "dist" / "MediaDownloader"
        exe_file = dist_dir / "MediaDownloader.exe"

        print("-" * 60)
        print("\n[УСПЕХ] Сборка успешно завершена!")
        print(f"Готовая папка приложения: {dist_dir}")
        print(f"Исполняемый файл: {exe_file}")
        print("\nВы можете запаковать эту папку в .zip или создать инсталлятор (Inno Setup) для передачи пользователям.")
    except subprocess.CalledProcessError as e:
        print(f"\n[ОШИБКА] Сборка завершилась с кодом ошибки {e.returncode}")


if __name__ == "__main__":
    build()
