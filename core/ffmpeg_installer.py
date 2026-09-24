from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

log = logging.getLogger("tts.ffmpeg_installer")

FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "ffmpeg"


def find_ffmpeg(configured_path: str) -> Optional[str]:
    if configured_path and configured_path.lower() != "ffmpeg":
        p = Path(configured_path)
        if p.is_file():
            return str(p)

    found = shutil.which(configured_path or "ffmpeg")
    if found:
        return found

    if VENDOR_DIR.exists():
        for exe in VENDOR_DIR.rglob("ffmpeg.exe"):
            return str(exe)

    return None


def _try_winget() -> Optional[str]:
    if platform.system() != "Windows":
        return None
    winget = shutil.which("winget")
    if not winget:
        log.info("wingetが見つからないため、直接ダウンロードにフォールバックします。")
        return None

    log.info("wingetでFFmpegの自動インストールを試みています...")
    try:
        result = subprocess.run(
            [
                winget, "install", "--id", "Gyan.FFmpeg", "-e",
                "--silent", "--accept-package-agreements", "--accept-source-agreements",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception:
        log.exception("winget実行中にエラーが発生しました")
        return None

    if result.returncode != 0:
        log.warning(
            "wingetでのFFmpegインストールに失敗しました（終了コード %s）: %s",
            result.returncode,
            (result.stdout + result.stderr).strip()[-500:],
        )
        return None

    found = shutil.which("ffmpeg")
    if found:
        return found

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if packages_dir.exists():
            for exe in packages_dir.rglob("ffmpeg.exe"):
                return str(exe)

    log.warning("wingetのインストールは成功しましたが、ffmpeg.exeの場所を特定できませんでした。")
    return None


def _try_apt() -> Optional[str]:
    if platform.system() != "Linux":
        return None
    apt_get = shutil.which("apt-get")
    if not apt_get:
        return None

    log.info("apt-getでFFmpegの自動インストールを試みています...")
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"

    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    sudo = shutil.which("sudo")
    base_cmd: list[str] = [] if is_root else ([sudo] if sudo else [])
    if not is_root and not sudo:
        log.warning("root権限がなく sudo も見つからないため、apt-getでのインストールを断念します。")
        return None

    try:
        subprocess.run(
            [*base_cmd, apt_get, "update"],
            capture_output=True, text=True, timeout=300, env=env, check=True,
        )
        subprocess.run(
            [*base_cmd, apt_get, "install", "-y", "ffmpeg"],
            capture_output=True, text=True, timeout=600, env=env, check=True,
        )
    except Exception:
        log.exception("apt-getでのFFmpegインストールに失敗しました")
        return None

    return shutil.which("ffmpeg")


def _download_file(url: str, dest: Path, timeout: int = 300) -> None:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (tts-bot ffmpeg installer)"})
    with urlopen(request, timeout=timeout) as response, open(dest, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def _try_direct_download() -> Optional[str]:
    if platform.system() != "Windows":
        return None

    log.info("FFmpeg公式ビルドを直接ダウンロードしています（数十MBあるため少し時間がかかります）...")
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = VENDOR_DIR / "ffmpeg.zip"
    try:
        _download_file(FFMPEG_DOWNLOAD_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(VENDOR_DIR)
    except Exception:
        log.exception("FFmpegのダウンロードまたは展開に失敗しました")
        return None
    finally:
        zip_path.unlink(missing_ok=True)

    for exe in VENDOR_DIR.rglob("ffmpeg.exe"):
        return str(exe)
    return None


def ensure_ffmpeg(configured_path: str) -> str:
    found = find_ffmpeg(configured_path)
    if found:
        log.info("FFmpegが見つかりました: %s", found)
        return found

    log.warning("FFmpegが見つかりません。自動インストールを試みます。")

    system = platform.system()
    if system == "Windows":
        found = _try_winget()
        if found:
            log.info("wingetでFFmpegをインストールしました: %s", found)
            return found

        found = _try_direct_download()
        if found:
            log.info("FFmpegを %s に自動インストールしました。", found)
            return found

        log.error(
            "FFmpegの自動インストールに失敗しました。"
            "https://www.gyan.dev/ffmpeg/builds/ から手動でダウンロードし、"
            ".envのFFMPEG_PATHに実行ファイルのパスを設定してください。"
        )
    elif system == "Linux":
        found = _try_apt()
        if found:
            log.info("apt-getでFFmpegをインストールしました: %s", found)
            return found

        log.error(
            "FFmpegの自動インストールに失敗しました。"
            "`sudo apt-get install -y ffmpeg` を手動で実行するか、"
            "Dockerを使う場合はDockerfileでffmpegを導入済みか確認してください。"
        )
    else:
        log.error(
            "このOS(%s)向けのFFmpeg自動インストールには対応していません。手動でインストールしてください。",
            system,
        )

    return configured_path or "ffmpeg"
