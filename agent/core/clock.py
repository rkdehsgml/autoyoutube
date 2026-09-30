"""시간·ID 도우미. DB 시각은 D1 datetime('now')와 같은 UTC 'YYYY-MM-DD HH:MM:SS' 문자열."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

DB_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """테스트용 시계. advance()로 시간을 넘긴다."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += timedelta(seconds=seconds)


def db_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(DB_TIME_FMT)


def parse_db_time(s: str) -> datetime:
    return datetime.strptime(s, DB_TIME_FMT).replace(tzinfo=timezone.utc)


def new_ulid(dt: datetime | None = None) -> str:
    """ULID (48비트 ms 타임스탬프 + 80비트 난수, Crockford base32 26자)."""
    ms = int((dt.timestamp() if dt else time.time()) * 1000)
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))
