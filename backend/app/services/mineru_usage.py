from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

from app.core.config import settings


class MineruQuotaError(RuntimeError):
    pass


_LOCK = threading.Lock()
_FILE = settings.data_dir / "mineru" / "usage.json"


def _today() -> str:
    return date.today().isoformat()


def _read() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def _write(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FILE)


def usage_today() -> int:
    with _LOCK:
        return int(_read().get(_today(), 0))


def reserve(pages: int, limit: int) -> int:
    if pages <= 0:
        return usage_today()
    with _LOCK:
        data = _read()
        today = _today()
        used = int(data.get(today, 0))
        if limit > 0 and used + pages > limit:
            raise MineruQuotaError(
                f"MinerU 每日页数配额不足：已用 {used} 页，本次需要 {pages} 页，上限 {limit} 页"
            )
        data[today] = used + pages
        _write(data)
        return data[today]


def release(pages: int) -> None:
    if pages <= 0:
        return
    with _LOCK:
        data = _read()
        today = _today()
        data[today] = max(0, int(data.get(today, 0)) - pages)
        _write(data)