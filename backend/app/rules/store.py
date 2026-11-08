from __future__ import annotations

import copy
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.db.models import RuleAudit, RuleRecord, RuleVersion, WhitelistEntry
from app.rules.loader import (
    CATEGORY_KEYS,
    RuleError,
    RuleSet,
    payload_sha256,
    ruleset_from_dict,
    validate_rules_dict,
)

RULES_PATH = PROJECT_ROOT / "rules" / "rules.yaml"

_CACHE: dict[int, tuple[str, RuleSet]] = {}
_CACHE_LOCK = threading.Lock()


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dumps(value: dict | list | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def invalidate_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _audit(
    db: Session,
    *,
    version_id: int | None,
    action: str,
    user_id: int | None,
    detail: dict | None = None,
) -> None:
    db.add(
        RuleAudit(
            version_id=version_id,
            action=action,
            user_id=user_id,
            detail_json=_dumps(detail),
            created_at=datetime.now(),
        )
    )


def seed_rules_if_empty(db: Session, path: Path | None = None) -> RuleVersion | None:
    active = db.scalar(select(RuleVersion).where(RuleVersion.status == "active"))
    if active:
        return active

    path = path or RULES_PATH
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_bytes())
    if not isinstance(data, dict):
        raise RuleError(f"{path} 根节点必须是对象")
    payload = copy.deepcopy(data)
    version = str(payload.get("version") or "1.1")
    if db.scalar(select(RuleVersion).where(RuleVersion.version == version)):
        version = next_version(db, version)
    payload["version"] = version
    row = create_version(
        db,
        payload,
        status="active",
        version=version,
        note="首次启动从 rules/rules.yaml 种子导入",
        user_id=None,
    )
    db.commit()
    return row


def next_version(db: Session, base: str) -> str:
    versions = list(db.scalars(select(RuleVersion.version)))
    match = re.fullmatch(r"(\d+)\.(\d+)", base or "")
    if match:
        major = int(match.group(1))
        minors: list[int] = []
        for value in versions:
            found = re.fullmatch(r"(\d+)\.(\d+)", value or "")
            if found and int(found.group(1)) == major:
                minors.append(int(found.group(2)))
        return f"{major}.{(max(minors) if minors else int(match.group(2))) + 1}"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{base}-draft-{stamp}"


def create_version(
    db: Session,
    payload: dict,
    *,
    status: str,
    version: str,
    note: str | None = None,
    user_id: int | None = None,
) -> RuleVersion:
    payload = copy.deepcopy(payload)
    payload["version"] = version
    errors = validate_rules_dict(payload)
    if errors:
        raise RuleError("; ".join(errors[:5]))
    if db.scalar(select(RuleVersion).where(RuleVersion.version == version)):
        raise RuleError(f"版本已存在: {version}")

    if status == "active":
        for row in db.scalars(select(RuleVersion).where(RuleVersion.status == "active")):
            row.status = "archived"
        db.flush()

    now = datetime.now()
    row = RuleVersion(
        version=version,
        status=status,
        global_json=_canonical(payload.get("global") or {}),
        content_json=_canonical(payload),
        sha256=payload_sha256(payload),
        note=note,
        created_by=user_id,
        created_at=now,
        updated_at=now,
        activated_at=now if status == "active" else None,
    )
    db.add(row)
    db.flush()
    _write_rows(db, row.id, payload)
    _audit(db, version_id=row.id, action=f"create_{status}", user_id=user_id, detail={"version": version})
    db.flush()
    invalidate_cache()
    return row


def _write_rows(db: Session, version_id: int, payload: dict) -> None:
    db.execute(delete(RuleRecord).where(RuleRecord.version_id == version_id))
    db.execute(delete(WhitelistEntry).where(WhitelistEntry.version_id == version_id))
    db.flush()

    order = 0
    for category in CATEGORY_KEYS:
        for item in payload.get(category) or []:
            match = item.get("match") or {}
            redact = item.get("redact") or {}
            db.add(
                RuleRecord(
                    version_id=version_id,
                    rule_id=str(item["id"]),
                    category=str(item.get("category") or category),
                    name=str(item.get("name") or item["id"]),
                    enabled=bool(item.get("enabled", True)),
                    confidence=float(item.get("confidence", 0.8)),
                    protect_seal=bool(item.get("protect_seal", False)),
                    match_type=str(match.get("type") or ""),
                    match_json=_canonical(match),
                    redact_json=_canonical(redact),
                    sort_order=order,
                )
            )
            order += 1

    for order, item in enumerate(payload.get("whitelist") or []):
        db.add(
            WhitelistEntry(
                version_id=version_id,
                whitelist_id=str(item["id"]),
                name=str(item.get("name") or item["id"]),
                type=str(item.get("type") or "value"),
                pattern=item.get("pattern"),
                keywords_json=_dumps(item.get("keywords")),
                context_keywords_json=_dumps(item.get("context_keywords")),
                exclude_checks_json=_dumps(item.get("exclude_if_checks")),
                detect=item.get("detect"),
                reason=item.get("reason"),
                sort_order=order,
            )
        )
    db.flush()


def payload_from_version(db: Session, row: RuleVersion) -> dict:
    payload = _loads(row.content_json, None)
    if isinstance(payload, dict):
        payload["version"] = row.version
        return payload

    rules = list(
        db.scalars(
            select(RuleRecord)
            .where(RuleRecord.version_id == row.id)
            .order_by(RuleRecord.sort_order, RuleRecord.id)
        )
    )
    whitelist_rows = list(
        db.scalars(
            select(WhitelistEntry)
            .where(WhitelistEntry.version_id == row.id)
            .order_by(WhitelistEntry.sort_order, WhitelistEntry.id)
        )
    )
    payload = {
        "version": row.version,
        "global": _loads(row.global_json, {}),
        "whitelist": [],
        "personal": [],
        "secret": [],
        "contact": [],
    }
    for item in whitelist_rows:
        entry = {"id": item.whitelist_id, "name": item.name, "type": item.type}
        if item.pattern:
            entry["pattern"] = item.pattern
        keywords = _loads(item.keywords_json, None)
        if keywords:
            entry["keywords"] = keywords
        context_keywords = _loads(item.context_keywords_json, None)
        if context_keywords:
            entry["context_keywords"] = context_keywords
        exclude_checks = _loads(item.exclude_checks_json, None)
        if exclude_checks:
            entry["exclude_if_checks"] = exclude_checks
        if item.detect:
            entry["detect"] = item.detect
        if item.reason:
            entry["reason"] = item.reason
        payload["whitelist"].append(entry)
    for item in rules:
        rule = {
            "id": item.rule_id,
            "name": item.name,
            "enabled": bool(item.enabled),
            "confidence": item.confidence,
            "protect_seal": bool(item.protect_seal),
            "match": _loads(item.match_json, {}),
            "redact": _loads(item.redact_json, {}),
        }
        payload.setdefault(item.category, []).append(rule)
    return payload


def save_payload(
    db: Session, row: RuleVersion, payload: dict, user_id: int | None = None
) -> RuleVersion:
    if row.status != "draft":
        raise RuleError("只有草稿版本可以编辑")
    payload = copy.deepcopy(payload)
    payload["version"] = row.version
    # 全局配置不通过规则 UI 修改，保存时保留原值
    payload["global"] = _loads(row.global_json, payload.get("global") or {})
    errors = validate_rules_dict(payload)
    if errors:
        raise RuleError("; ".join(errors[:5]))

    row.content_json = _canonical(payload)
    row.global_json = _canonical(payload.get("global") or {})
    row.sha256 = payload_sha256(payload)
    row.updated_at = datetime.now()
    _write_rows(db, row.id, payload)
    _audit(db, version_id=row.id, action="save_draft", user_id=user_id, detail={"version": row.version})
    db.flush()
    return row


def activate_version(db: Session, row: RuleVersion, user_id: int | None = None) -> RuleVersion:
    if row.status == "archived":
        raise RuleError("历史版本请使用回滚")
    if row.status == "active":
        return row
    for current in db.scalars(select(RuleVersion).where(RuleVersion.status == "active")):
        current.status = "archived"
    db.flush()
    row.status = "active"
    row.activated_at = datetime.now()
    row.updated_at = datetime.now()
    _audit(db, version_id=row.id, action="activate", user_id=user_id, detail={"version": row.version})
    db.flush()
    invalidate_cache()
    return row


def get_active_version(db: Session) -> RuleVersion | None:
    return db.scalar(select(RuleVersion).where(RuleVersion.status == "active"))


def get_active_ruleset(db: Session) -> RuleSet:
    row = get_active_version(db)
    if row is None:
        row = seed_rules_if_empty(db)
    if row is None:
        raise RuleError("没有可用的规则版本，请先导入 rules.yaml")

    with _CACHE_LOCK:
        cached = _CACHE.get(row.id)
        if cached and cached[0] == row.sha256:
            return cached[1]

    payload = payload_from_version(db, row)
    ruleset = ruleset_from_dict(
        payload,
        source_path=f"sqlite:{row.version}",
        sha256=row.sha256,
    )
    with _CACHE_LOCK:
        _CACHE[row.id] = (row.sha256, ruleset)
    return ruleset


def get_ruleset_for_version(db: Session, row: RuleVersion) -> RuleSet:
    payload = payload_from_version(db, row)
    return ruleset_from_dict(
        payload,
        source_path=f"sqlite:{row.version}",
        sha256=row.sha256,
    )


def export_yaml(payload: dict) -> str:
    return yaml.safe_dump(
        copy.deepcopy(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )