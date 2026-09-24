import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    return float(raw) if raw else default


def _path(name: str, default: str) -> str:
    p = Path((os.getenv(name) or "").strip() or default)
    return str(p if p.is_absolute() else BASE_DIR / p)


DISCORD_TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
VOICEVOX_URL = (os.getenv("VOICEVOX_URL") or "http://127.0.0.1:50021").strip().rstrip("/")
FFMPEG_PATH = (os.getenv("FFMPEG_PATH") or "ffmpeg").strip()
DB_PATH = _path("DB_PATH", "data/bot.db")
LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()

DEFAULT_SPEAKER_ID = _int("DEFAULT_SPEAKER_ID", 3)
MAX_MESSAGE_LENGTH = _int("MAX_MESSAGE_LENGTH", 200)
TTS_CHUNK_LENGTH = max(20, _int("TTS_CHUNK_LENGTH", 60))

DEV_GUILD_ID = (os.getenv("DEV_GUILD_ID") or "").strip() or None

PRESENCE_INTERVAL = max(10, _int("PRESENCE_INTERVAL", 15))

SUPPORT_URL = (os.getenv("SUPPORT_URL") or "").strip()

SOUND_DUCK_VOLUME = max(0.0, min(1.0, _float("SOUND_DUCK_VOLUME", 0.4)))
SOUND_MAX_FILE_SIZE = _int("SOUND_MAX_FILE_SIZE_MB", 20) * 1024 * 1024
SOUND_MAX_DURATION = _int("SOUND_MAX_DURATION_SECONDS", 600)

QUAKE_ENABLED = _bool("QUAKE_ENABLED", True)
QUAKE_WS_URL = (os.getenv("QUAKE_WS_URL") or "wss://api.p2pquake.net/v2/ws").strip()
QUAKE_API_URL = (os.getenv("QUAKE_API_URL") or "https://api.p2pquake.net/v2/history").strip()
QUAKE_POLL_INTERVAL = max(10, _int("QUAKE_POLL_INTERVAL", 30))
QUAKE_ALERT_SOUND = _path("QUAKE_ALERT_SOUND", "assets/alert.mp3")
QUAKE_DEFAULT_MIN_SCALE = _int("QUAKE_DEFAULT_MIN_SCALE", 40)
