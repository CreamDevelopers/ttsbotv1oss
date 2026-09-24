# 地震速報の受信と読み上げ文を Discord なしで確認する: python tools/quake_test.py [--sample | --watch]
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from core.earthquake import EarthquakeMonitor, QuakeEvent, parse_event, sample_event  # noqa: E402
from core.text_processor import split_text  # noqa: E402


def show(event: QuakeEvent) -> None:
    text = event.speech_text()
    print("-" * 60)
    print(f"種別   : {event.title}")
    print(f"震源地 : {event.hypocenter or '不明'}")
    print(f"最大震度: 震度{event.scale_text}")
    print(f"読み上げ: {text}")
    chunks = split_text(text, config.TTS_CHUNK_LENGTH)
    print(f"分割    : {len(chunks)}チャンク（1チャンク最大{config.TTS_CHUNK_LENGTH}文字）")
    for i, chunk in enumerate(chunks, 1):
        print(f"  [{i}] {chunk}")


async def run_history(monitor: EarthquakeMonitor, limit: int) -> None:
    payloads = await monitor.fetch_history(limit=limit)
    if not payloads:
        print("地震情報を取得できませんでした。APIに接続できているか確認してください。")
        return
    for payload in payloads:
        event = parse_event(payload)
        if event is not None:
            show(event)


async def run_watch(monitor: EarthquakeMonitor) -> None:
    async def listener(event: QuakeEvent) -> None:
        show(event)

    monitor.add_listener(listener)
    await monitor.start()
    print(f"待ち受け中: {config.QUAKE_WS_URL} （Ctrl+Cで終了）")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass


async def main_async(args: argparse.Namespace) -> None:
    if args.sample:
        show(sample_event(50, kind="eew"))
        show(sample_event(60, kind="info"))
        return

    monitor = EarthquakeMonitor(
        config.QUAKE_WS_URL, config.QUAKE_API_URL, poll_interval=config.QUAKE_POLL_INTERVAL
    )
    try:
        if args.watch:
            await run_watch(monitor)
        else:
            await run_history(monitor, args.limit)
    finally:
        await monitor.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="地震速報の動作確認")
    parser.add_argument("--sample", action="store_true", help="サンプル地震で読み上げ文を確認する")
    parser.add_argument("--watch", action="store_true", help="速報が届くまで待ち受ける")
    parser.add_argument("--limit", type=int, default=3, help="取得する件数（既定: 3）")
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n終了しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
