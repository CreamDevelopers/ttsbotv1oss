from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE_PATH = BASE_DIR / ".env.example"

VOICEVOX_IMAGE = "voicevox/voicevox_engine:cpu-latest"
VOICEVOX_CONTAINER = "yomiage-voicevox"


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def set_env_value(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines() if ENV_PATH.exists() else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_token() -> None:
    if not ENV_PATH.exists():
        if ENV_EXAMPLE_PATH.exists():
            shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
        else:
            ENV_PATH.write_text("", encoding="utf-8")

    if read_env().get("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN"):
        return

    print()
    print("DiscordのBOTトークンを設定します。")
    print("https://discord.com/developers/applications でアプリを作り、")
    print("Bot → Reset Token で表示されたトークンを貼り付けてください。")
    print("（Bot の MESSAGE CONTENT INTENT と SERVER MEMBERS INTENT もONにしておいてください）")
    print()
    while True:
        try:
            token = input("DISCORD_TOKEN: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if token:
            break
    set_env_value("DISCORD_TOKEN", token)
    print(".env に保存しました。変更したいときは .env を編集してください。")
    print()


def voicevox_url() -> str:
    return (os.getenv("VOICEVOX_URL") or read_env().get("VOICEVOX_URL") or "http://127.0.0.1:50021").rstrip("/")


def voicevox_alive(url: str) -> bool:
    try:
        with urlopen(f"{url}/version", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_voicevox(url: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if voicevox_alive(url):
            return True
        time.sleep(2)
    return False


def find_windows_engine() -> Path | None:
    candidates = []
    local = os.getenv("LOCALAPPDATA")
    if local:
        candidates += [
            Path(local) / "Programs" / "VOICEVOX" / "vv-engine" / "run.exe",
            Path(local) / "Programs" / "VOICEVOX" / "run.exe",
        ]
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.getenv(env)
        if root:
            candidates += [
                Path(root) / "VOICEVOX" / "vv-engine" / "run.exe",
                Path(root) / "VOICEVOX" / "run.exe",
            ]
    candidates.append(BASE_DIR / "voicevox_engine" / "run.exe")
    return next((p for p in candidates if p.is_file()), None)


def start_windows_engine(port: int) -> subprocess.Popen | None:
    engine = find_windows_engine()
    if engine is None:
        return None
    print(f"VOICEVOXエンジンを起動します: {engine}")
    return subprocess.Popen(
        [str(engine), "--host", "127.0.0.1", "--port", str(port)],
        cwd=engine.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def start_docker_engine(port: int) -> bool:
    docker = shutil.which("docker")
    if not docker:
        return False
    try:
        if subprocess.run([docker, "info"], capture_output=True, timeout=20).returncode != 0:
            print("Dockerはありますが、使える状態ではありません（権限かデーモンを確認してください）。")
            return False
        exists = subprocess.run(
            [docker, "container", "inspect", VOICEVOX_CONTAINER], capture_output=True, timeout=20
        ).returncode == 0
        if exists:
            print("VOICEVOXエンジンのコンテナを起動します。")
            cmd = [docker, "start", VOICEVOX_CONTAINER]
        else:
            print("VOICEVOXエンジンをDockerで起動します（初回はイメージの取得に数分かかります）。")
            cmd = [
                docker, "run", "-d", "--name", VOICEVOX_CONTAINER, "--restart", "unless-stopped",
                "-p", f"127.0.0.1:{port}:50021", VOICEVOX_IMAGE,
            ]
        return subprocess.run(cmd, timeout=900).returncode == 0
    except Exception as e:
        print(f"Dockerでの起動に失敗しました: {e}")
        return False


def ensure_voicevox() -> subprocess.Popen | None:
    url = voicevox_url()
    if voicevox_alive(url):
        print(f"VOICEVOXエンジン: {url} に接続できました。")
        return None

    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        print(f"VOICEVOXエンジン（{url}）に接続できません。起動しているか確認してください。")
        return None
    port = parsed.port or 50021

    proc = None
    started = False
    if platform.system() == "Windows":
        proc = start_windows_engine(port)
        started = proc is not None
    if not started:
        started = start_docker_engine(port)

    if started:
        print("VOICEVOXエンジンの起動を待っています...")
        if wait_voicevox(url, 180):
            print("VOICEVOXエンジンが起動しました。")
            return proc
        print("VOICEVOXエンジンの起動を確認できませんでした。BOTはそのまま起動します。")
        return proc

    print()
    print("VOICEVOXエンジンが見つかりませんでした。次のどちらかを行ってから起動し直してください。")
    if platform.system() == "Windows":
        print("  - VOICEVOX（https://voicevox.hiroshiba.jp/）をインストールする")
        print("  - Docker Desktop をインストールする")
    else:
        print("  - Dockerをインストールする（sudo apt install docker.io など）")
        print("  - VOICEVOXエンジンを自分で起動し、.env の VOICEVOX_URL をそのURLにする")
    print("このままBOTを起動しますが、読み上げはできません。")
    print()
    return None


def main() -> int:
    os.chdir(BASE_DIR)
    ensure_token()
    engine = ensure_voicevox()
    bot = subprocess.Popen([sys.executable, str(BASE_DIR / "main.py")])
    try:
        return bot.wait()
    except KeyboardInterrupt:
        try:
            # Ctrl+C は BOT 側にも届いているので、切断処理が終わるのを待つ
            return bot.wait(timeout=15)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            bot.kill()
            return 1
    finally:
        if engine is not None and engine.poll() is None:
            engine.terminate()


if __name__ == "__main__":
    sys.exit(main())
