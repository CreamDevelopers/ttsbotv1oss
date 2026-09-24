from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from core import timeutil
from typing import Any, Awaitable, Callable, Optional

import aiohttp

log = logging.getLogger("tts.earthquake")

CODE_QUAKE = 551
CODE_EEW = 556

SCALE_LABELS: dict[int, str] = {
    10: "1",
    20: "2",
    30: "3",
    40: "4",
    45: "5弱",
    46: "5弱以上",
    50: "5強",
    55: "6弱",
    60: "6強",
    70: "7",
}

SELECTABLE_SCALES: list[int] = [10, 20, 30, 40, 45, 50, 55, 60, 70]

TSUNAMI_LABELS: dict[str, str] = {
    "None": "この地震による津波の心配はありません",
    "Unknown": "津波の情報は入っていません",
    "Checking": "津波の有無は現在調査中です",
    "NonEffective": "若干の海面変動が予想されますが、被害の心配はありません",
    "Watch": "津波注意報が発表されています",
    "Warning": "津波警報が発表されています。ただちに高台へ避難してください",
}

ISSUE_TYPE_LABELS: dict[str, str] = {
    "ScalePrompt": "震度速報",
    "Destination": "震源情報",
    "ScaleAndDestination": "震源・震度情報",
    "DetailScale": "各地の震度",
    "Foreign": "遠地地震情報",
    "Other": "地震情報",
}


def scale_label(scale: Optional[int]) -> str:
    if scale is None:
        return "不明"
    return SCALE_LABELS.get(scale, "不明")


def normalize_scale(scale: Any) -> int:
    try:
        value = int(scale)
    except (TypeError, ValueError):
        return -1
    return value if value in SCALE_LABELS else -1


def _format_time(raw: str) -> str:
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return timeutil.format_time_of_day(dt)
    return raw


def _format_depth(depth: Any) -> Optional[str]:
    try:
        value = int(depth)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    if value == 0:
        return "ごく浅い"
    return f"およそ{value}キロメートル"


def _format_magnitude(magnitude: Any) -> Optional[str]:
    try:
        value = float(magnitude)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return f"{value:.1f}"


@dataclass
class QuakeEvent:
    id: str
    kind: str
    max_scale: int = -1
    hypocenter: str = ""
    magnitude: Optional[str] = None
    depth: Optional[str] = None
    occurred_at: str = ""
    tsunami: Optional[str] = None
    issue_type: Optional[str] = None
    areas: list[str] = field(default_factory=list)
    event_id: Optional[str] = None
    serial: Optional[int] = None
    is_test: bool = False
    is_cancelled: bool = False

    @property
    def is_eew(self) -> bool:
        return self.kind == "eew"

    @property
    def title(self) -> str:
        if self.is_cancelled:
            return "緊急地震速報（取り消し）" if self.is_eew else "地震情報（取り消し）"
        if self.is_eew:
            return "緊急地震速報（警報）"
        return ISSUE_TYPE_LABELS.get(self.issue_type or "", "地震情報")

    @property
    def scale_text(self) -> str:
        return scale_label(self.max_scale)

    def speech_text(self) -> str:
        if self.is_cancelled:
            head = "緊急地震速報" if self.is_eew else "地震情報"
            return f"さきほどの{head}は取り消されました。"

        parts: list[str] = []
        if self.is_test:
            parts.append("これはテストです。")

        if self.is_eew:
            parts.append("緊急地震速報です。")
            where = self.hypocenter or "震源地不明"
            parts.append(f"{where}で地震が発生しました。")
            if self.max_scale > 0:
                parts.append(f"予想される最大震度は{self.scale_text}です。")
            if self.magnitude:
                parts.append(f"地震の規模はマグニチュード{self.magnitude}と推定されます。")
            if self.areas:
                parts.append("対象の地域は、" + "、".join(self.areas) + "です。")
            parts.append("強い揺れに警戒してください。")
        else:
            parts.append("地震情報です。")
            when = f"{self.occurred_at}、" if self.occurred_at else ""
            where = self.hypocenter or "震源地不明の場所"
            parts.append(f"{when}{where}を震源とする地震がありました。")
            if self.max_scale > 0:
                parts.append(f"最大震度は{self.scale_text}です。")
            if self.magnitude:
                parts.append(f"地震の規模はマグニチュード{self.magnitude}。")
            if self.depth:
                parts.append(f"震源の深さは{self.depth}です。")
            if self.areas:
                parts.append("主な地域は、" + "、".join(self.areas) + "。")
            if self.tsunami:
                parts.append(f"{self.tsunami}。")

        return "".join(parts)


def _eew_areas(payload: dict[str, Any]) -> tuple[int, list[str]]:
    max_scale = -1
    ranked: list[tuple[int, str]] = []
    for area in payload.get("areas") or []:
        scale = normalize_scale(area.get("scaleFrom"))
        to_scale = normalize_scale(area.get("scaleTo"))
        if to_scale > scale:
            scale = to_scale
        name = (area.get("name") or area.get("pref") or "").strip()
        if not name:
            continue
        ranked.append((scale, name))
        max_scale = max(max_scale, scale)

    ranked.sort(key=lambda item: item[0], reverse=True)
    names: list[str] = []
    for _, name in ranked:
        if name not in names:
            names.append(name)
    return max_scale, names


def _quake_areas(payload: dict[str, Any], max_scale: int) -> list[str]:
    names: list[str] = []
    for point in payload.get("points") or []:
        if normalize_scale(point.get("scale")) != max_scale:
            continue
        name = (point.get("addr") or point.get("pref") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def parse_event(payload: dict[str, Any]) -> Optional[QuakeEvent]:
    code = payload.get("code")
    identifier = str(payload.get("id") or payload.get("_id") or "")

    if code == CODE_EEW:
        earthquake = payload.get("earthquake") or {}
        hypocenter = earthquake.get("hypocenter") or {}
        issue = payload.get("issue") or {}
        max_scale, areas = _eew_areas(payload)
        serial = issue.get("serial")
        try:
            serial = int(serial) if serial is not None else None
        except (TypeError, ValueError):
            serial = None
        return QuakeEvent(
            id=identifier,
            kind="eew",
            max_scale=max_scale,
            hypocenter=(hypocenter.get("name") or "").strip(),
            magnitude=_format_magnitude(hypocenter.get("magnitude")),
            depth=_format_depth(hypocenter.get("depth")),
            occurred_at=_format_time(earthquake.get("originTime") or ""),
            areas=areas[:8],
            event_id=issue.get("eventId"),
            serial=serial,
            is_test=bool(payload.get("test")),
            is_cancelled=bool(payload.get("cancelled")),
        )

    if code == CODE_QUAKE:
        earthquake = payload.get("earthquake") or {}
        hypocenter = earthquake.get("hypocenter") or {}
        issue = payload.get("issue") or {}
        max_scale = normalize_scale(earthquake.get("maxScale"))
        tsunami = TSUNAMI_LABELS.get(earthquake.get("domesticTsunami") or "")
        return QuakeEvent(
            id=identifier,
            kind="info",
            max_scale=max_scale,
            hypocenter=(hypocenter.get("name") or "").strip(),
            magnitude=_format_magnitude(hypocenter.get("magnitude")),
            depth=_format_depth(hypocenter.get("depth")),
            occurred_at=_format_time(earthquake.get("time") or payload.get("time") or ""),
            tsunami=tsunami,
            issue_type=issue.get("type"),
            areas=_quake_areas(payload, max_scale)[:8],
            is_test=False,
            is_cancelled=(issue.get("correct") or "") == "Cancel",
        )

    return None


def sample_event(scale: int, *, kind: str = "info") -> QuakeEvent:
    occurred_at = timeutil.format_time_of_day()
    if kind == "eew":
        return QuakeEvent(
            id="test-eew",
            kind="eew",
            max_scale=scale,
            hypocenter="テスト県沖",
            magnitude="6.5",
            depth="およそ10キロメートル",
            occurred_at=occurred_at,
            areas=["テスト県東部", "テスト県西部"],
            event_id="test",
            serial=1,
            is_test=True,
        )
    return QuakeEvent(
        id="test-info",
        kind="info",
        max_scale=scale,
        hypocenter="テスト県沖",
        magnitude="6.5",
        depth="およそ10キロメートル",
        occurred_at=occurred_at,
        tsunami="この地震による津波の心配はありません",
        issue_type="ScaleAndDestination",
        areas=["テスト市", "テスト町"],
        is_test=True,
    )


Listener = Callable[[QuakeEvent], Awaitable[None]]


class EarthquakeMonitor:
    _BACKOFF_MIN = 3
    _BACKOFF_MAX = 60

    def __init__(
        self,
        ws_url: str,
        api_url: str,
        *,
        poll_interval: int = 30,
        codes: tuple[int, ...] = (CODE_QUAKE, CODE_EEW),
    ):
        self.ws_url = ws_url
        self.api_url = api_url.rstrip("/")
        self.poll_interval = max(10, poll_interval)
        self.codes = codes
        self._listeners: list[Listener] = []
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._seen: set[str] = set()
        self._seeded = False
        self.connected = False
        self.last_event_at: Optional[datetime] = None

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="earthquake-monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._session and not self._session.closed:
            await self._session.close()
        self.connected = False

    def _remember(self, identifier: str) -> bool:
        if not identifier or identifier in self._seen:
            return False
        self._seen.add(identifier)
        if len(self._seen) > 500:
            for old in list(self._seen)[:200]:
                self._seen.discard(old)
        return True

    async def _emit(self, payload: dict[str, Any]) -> None:
        event = parse_event(payload)
        if event is None:
            return
        if not self._remember(event.id or f"{event.kind}:{event.event_id}:{event.serial}"):
            return
        self.last_event_at = timeutil.now()
        for listener in self._listeners:
            try:
                await listener(event)
            except Exception:
                log.exception("地震速報の通知処理でエラーが発生しました")

    async def _run(self) -> None:
        backoff = self._BACKOFF_MIN
        while True:
            try:
                await self._seed_seen()
                await self._listen_ws()
                backoff = self._BACKOFF_MIN
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("地震情報APIのWebSocket接続が切れました: %s", exc)
            finally:
                self.connected = False

            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("地震情報APIの取得に失敗しました", exc_info=True)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._BACKOFF_MAX)

    async def _seed_seen(self) -> None:
        if self._seeded:
            return
        self._seeded = True
        try:
            for payload in await self.fetch_history(limit=10):
                identifier = str(payload.get("id") or payload.get("_id") or "")
                if identifier:
                    self._seen.add(identifier)
        except Exception:
            log.warning("起動時の地震情報の取得に失敗しました", exc_info=True)

    async def _listen_ws(self) -> None:
        session = await self._ensure_session()
        async with session.ws_connect(self.ws_url, heartbeat=30) as ws:
            self.connected = True
            log.info("地震情報APIに接続しました: %s", self.ws_url)
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    await self._emit(payload)

    async def _poll_once(self) -> None:
        for payload in await self.fetch_history(limit=3):
            await self._emit(payload)

    async def fetch_history(self, *, limit: int = 5) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        timeout = aiohttp.ClientTimeout(total=15)
        results: list[dict[str, Any]] = []
        for code in self.codes:
            params = {"codes": str(code), "limit": str(limit)}
            async with session.get(self.api_url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    log.warning("地震情報APIが %s を返しました (code=%s)", resp.status, code)
                    continue
                data = await resp.json()
            if isinstance(data, list):
                results.extend(item for item in data if isinstance(item, dict))
        results.sort(key=lambda item: str(item.get("time") or ""))
        return results
