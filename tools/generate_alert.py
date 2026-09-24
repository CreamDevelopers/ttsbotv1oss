# 地震速報の警報音 assets/alert.mp3 を作り直す: python tools/generate_alert.py
from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = BASE_DIR / "assets" / "alert.mp3"

SAMPLE_RATE = 44100
TONE_HIGH = 1046.5
TONE_LOW = 783.99
BEEP_SECONDS = 0.22
GAP_SECONDS = 0.06
REPEAT = 3
TAIL_SECONDS = 0.25
AMPLITUDE = 0.62
FADE_SECONDS = 0.012


def _beep(frequency: float, seconds: float) -> list[float]:
    total = int(SAMPLE_RATE * seconds)
    fade = max(1, int(SAMPLE_RATE * FADE_SECONDS))
    samples: list[float] = []
    for i in range(total):
        t = i / SAMPLE_RATE
        value = math.sin(2 * math.pi * frequency * t) + 0.35 * math.sin(
            2 * math.pi * frequency * 1.5 * t
        )
        value /= 1.35
        if i < fade:
            value *= i / fade
        elif i > total - fade:
            value *= (total - i) / fade
        samples.append(value * AMPLITUDE)
    return samples


def _silence(seconds: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * seconds)


def build_samples() -> list[float]:
    samples: list[float] = []
    for _ in range(REPEAT):
        samples += _beep(TONE_HIGH, BEEP_SECONDS)
        samples += _silence(GAP_SECONDS)
        samples += _beep(TONE_LOW, BEEP_SECONDS)
        samples += _silence(GAP_SECONDS)
    samples += _silence(TAIL_SECONDS)
    return samples


def write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        frames = b"".join(
            struct.pack("<h", max(-32768, min(32767, int(value * 32767)))) for value in samples
        )
        wav.writeframes(frames)


def to_mp3(wav_path: Path, mp3_path: Path, ffmpeg: str) -> None:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame",
         "-b:a", "128k", str(mp3_path)],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="地震速報の警報音を生成します")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="出力先ファイル")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpegの実行ファイルパス")
    args = parser.parse_args()

    samples = build_samples()
    output: Path = args.output

    if output.suffix.lower() == ".wav":
        write_wav(output, samples)
        print(f"生成しました: {output}")
        return 0

    ffmpeg = shutil.which(args.ffmpeg) or args.ffmpeg
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "alert.wav"
        write_wav(wav_path, samples)
        try:
            to_mp3(wav_path, output, ffmpeg)
        except (OSError, subprocess.CalledProcessError) as exc:
            fallback = output.with_suffix(".wav")
            write_wav(fallback, samples)
            print(f"ffmpegが使えなかったためWAVで出力しました: {fallback} ({exc})", file=sys.stderr)
            return 1
    print(f"生成しました: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
