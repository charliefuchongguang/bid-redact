from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.core.config import PROJECT_ROOT, settings

TOKEN_TTL_MONTHS = 3
TOKEN_KEY = "MINERU_API_TOKEN"
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
META_PATH = settings.data_dir / "system" / "mineru_token.json"


def mask_token(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def token_digest(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def add_months(value: datetime, months: int) -> datetime:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _now() -> datetime:
    return datetime.now().astimezone()


def _read_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        data = json.loads(META_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta(data: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = META_PATH.parent / f"{META_PATH.name}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, META_PATH)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.astimezone()
    except Exception:
        return None


def _env_mtime() -> datetime | None:
    try:
        return datetime.fromtimestamp(ENV_PATH.stat().st_mtime).astimezone()
    except OSError:
        return None


def _write_env_token(token: str) -> None:
    if not ENV_PATH.exists() and ENV_EXAMPLE_PATH.exists():
        shutil.copy2(ENV_EXAMPLE_PATH, ENV_PATH)
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, ENV_PATH.parent / f"{ENV_PATH.name}.bak")
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    found = False
    for index, line in enumerate(lines):
        if re.match(r"^\s*MINERU_API_TOKEN\s*=", line):
            lines[index] = f"{TOKEN_KEY}={token}"
            found = True
            break
    if not found:
        lines.append(f"{TOKEN_KEY}={token}")
    content = "\n".join(lines) + "\n"
    tmp = ENV_PATH.parent / f"{ENV_PATH.name}.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, ENV_PATH)


def _warning(days_left: int | None) -> str:
    if days_left is None:
        return "unknown"
    if days_left < 0:
        return "expired"
    if days_left <= 7:
        return "urgent"
    if days_left <= 30:
        return "soon"
    return "ok"


def token_status() -> dict:
    token = (settings.mineru_api_token or "").strip()
    if not token:
        return {
            "mineru_token_configured": False,
            "mineru_token_masked": "",
            "token_set_at": None,
            "token_expires_at": None,
            "token_days_left": None,
            "token_expiry_source": "unknown",
            "token_expiry_warning": "unknown",
        }

    meta = _read_meta()
    digest = token_digest(token)
    source = "recorded"
    set_at = None
    if meta.get("token_sha256") == digest:
        set_at = _parse_time(meta.get("set_at"))
        source = str(meta.get("source") or "recorded")
    if set_at is None:
        set_at = _env_mtime()
        source = "env_mtime" if set_at else "unknown"

    expires_at = add_months(set_at, TOKEN_TTL_MONTHS) if set_at else None
    days_left = None
    if expires_at:
        days_left = (expires_at - _now()).days

    return {
        "mineru_token_configured": True,
        "mineru_token_masked": mask_token(token),
        "token_set_at": set_at.isoformat() if set_at else None,
        "token_expires_at": expires_at.isoformat() if expires_at else None,
        "token_days_left": days_left,
        "token_expiry_source": source,
        "token_expiry_warning": _warning(days_left),
    }


def save_mineru_token(raw: str) -> dict:
    token = (raw or "").strip()
    if not token:
        raise ValueError("Token 不能为空")
    if len(token) < 8 or len(token) > 200 or re.search(r"\s", token):
        raise ValueError("Token 格式不正确")

    old_token = (settings.mineru_api_token or "").strip()
    old_digest = token_digest(old_token) if old_token else ""
    new_digest = token_digest(token)
    meta = _read_meta()

    if old_digest == new_digest and old_digest:
        if meta.get("token_sha256") == new_digest:
            set_at = _parse_time(meta.get("set_at")) or _now()
            source = str(meta.get("source") or "ui")
        else:
            set_at = _env_mtime() or _now()
            source = "env_mtime" if set_at else "unknown"
    else:
        set_at = _now()
        source = "ui"

    _write_env_token(token)
    settings.mineru_api_token = token
    os.environ[TOKEN_KEY] = token
    expires_at = add_months(set_at, TOKEN_TTL_MONTHS)
    _write_meta(
        {
            "token_sha256": new_digest,
            "set_at": set_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "source": source,
        }
    )
    return token_status()


def clear_mineru_token() -> dict:
    _write_env_token("")
    settings.mineru_api_token = ""
    os.environ[TOKEN_KEY] = ""
    META_PATH.unlink(missing_ok=True)
    return token_status()