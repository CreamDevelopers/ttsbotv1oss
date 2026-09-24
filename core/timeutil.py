from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

JST = timezone(timedelta(hours=9), "JST")

DEFAULT_TZ_NAME = "Asia/Tokyo"


def now() -> datetime:
    return datetime.now(JST)


def to_jst(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, JST)


def format_datetime(value: Optional[float | datetime]) -> str:
    if value is None:
        return "—"
    dt = value.astimezone(JST) if isinstance(value, datetime) else to_jst(value)
    # %-m は Windows で使えない
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"


def format_time_of_day(dt: Optional[datetime] = None) -> str:
    dt = dt or now()
    return f"{dt.month}月{dt.day}日{dt.hour}時{dt.minute}分ごろ"


def setup_process_timezone() -> None:
    os.environ.setdefault("TZ", DEFAULT_TZ_NAME)
    if hasattr(time, "tzset"):
        time.tzset()


def configure_logging(level: str) -> None:
    setup_process_timezone()
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S JST",
    )
    # クラス属性に関数をそのまま入れると self が渡ってしまう
    logging.Formatter.converter = staticmethod(lambda ts: to_jst(ts).timetuple())
