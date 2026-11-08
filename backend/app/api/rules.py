from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.models import RuleRecord, RuleVersion, User, WhitelistEntry
from app.db.session import get_db
from app.rules.loader import RuleError, parse_rules_text, validate_rules_dict
from app.rules.store import (
    activate_version,
    create_version,
    export_yaml,
    get_active_version,
    get_ruleset_for_version,
    next_version,
    payload_from_version,
    save_payload,
    seed_rules_if_empty,
)
from app.rules.text_test import run_text_test

router = APIRouter(prefix="/admin/rules", tags=["admin-rules"])


class VersionOut(BaseModel):
    id: int
    version: str
    status: str
    sha256: str
    note: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    rule_count: int
    whitelist_count: int


class VersionDetailOut(BaseModel):
    version: VersionOut
    payload: dict
    yaml: str


class CreateDraftIn(BaseModel):
    version: str | None = None
    note: str | None = None


class SaveIn(BaseModel):
    format: str = "json"
    content: str


class ImportIn(BaseModel):
    yaml: str
    version: str | None = None
    note: str | None = None


class TestIn(BaseModel):
    text: str
    version_id: int | None = None


class ConvertIn(BaseModel):
    format: str
    content: str


def _version(db: Session, version_id: int) -> RuleVersion:
    row = db.get(RuleVersion, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="规则版本不存在")
    return row


def _version_out(db: Session, row: RuleVersion) -> VersionOut:
    rule_count = db.scalar(
        select(func.count(RuleRecord.id)).where(RuleRecord.version_id == row.id)
    )
    whitelist_count = db.scalar(
        select(func.count(WhitelistEntry.id)).where(WhitelistEntry.version_id == row.id)
    )
    return VersionOut(
        id=row.id,
        version=row.version,
        status=row.status,
        sha256=row.sha256,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        activated_at=row.activated_at,
        rule_count=int(rule_count or 0),
        whitelist_count=int(whitelist_count or 0),
    )


def _active(db: Session) -> RuleVersion:
    row = get_active_version(db)
    if row is None:
        row = seed_rules_if_empty(db)
    if row is None:
        raise HTTPException(status_code=404, detail="尚未初始化规则库")
    return row


def _parse_content(content: str, fmt: str) -> dict:
    if fmt == "yaml":
        try:
            return parse_rules_text(content)
        except RuleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if fmt != "json":
        raise HTTPException(status_code=400, detail="format 仅支持 json 或 yaml")
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="规则根节点必须是对象")
    return data


@router.get("/active", response_model=VersionDetailOut)
def active_rules(
    _admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> VersionDetailOut:
    row = _active(db)
    payload = payload_from_version(db, row)
    return VersionDetailOut(
        version=_version_out(db, row),
        payload=payload,
        yaml=export_yaml(payload),
    )


@router.get("/versions", response_model=list[VersionOut])
def list_versions(
    _admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[VersionOut]:
    rows = db.scalars(
        select(RuleVersion).order_by(RuleVersion.created_at.desc(), RuleVersion.id.desc())
    ).all()
    return [_version_out(db, row) for row in rows]


@router.get("/versions/{version_id}", response_model=VersionDetailOut)
def version_detail(
    version_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionDetailOut:
    row = _version(db, version_id)
    payload = payload_from_version(db, row)
    return VersionDetailOut(
        version=_version_out(db, row),
        payload=payload,
        yaml=export_yaml(payload),
    )


@router.post("/versions", response_model=VersionDetailOut, status_code=201)
def create_draft(
    data: CreateDraftIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionDetailOut:
    data = data or CreateDraftIn()
    base = _active(db)
    payload = payload_from_version(db, base)
    version = data.version or next_version(db, base.version)
    try:
        row = create_version(
            db,
            payload,
            status="draft",
            version=version,
            note=data.note or f"基于 {base.version} 创建",
            user_id=admin.id,
        )
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    result = payload_from_version(db, row)
    return VersionDetailOut(
        version=_version_out(db, row),
        payload=result,
        yaml=export_yaml(result),
    )


@router.put("/versions/{version_id}", response_model=VersionDetailOut)
def save_version(
    version_id: int,
    data: SaveIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionDetailOut:
    row = _version(db, version_id)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="active/历史版本只读，请先创建草稿")
    payload = _parse_content(data.content, data.format)
    try:
        save_payload(db, row, payload, user_id=admin.id)
    except RuleError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    result = payload_from_version(db, row)
    return VersionDetailOut(
        version=_version_out(db, row),
        payload=result,
        yaml=export_yaml(result),
    )


@router.post("/versions/{version_id}/validate")
def validate_version(
    version_id: int,
    data: SaveIn | None = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    row = _version(db, version_id)
    if data is not None:
        try:
            payload = _parse_content(data.content, data.format)
        except HTTPException as exc:
            return {"valid": False, "errors": [str(exc.detail)]}
    else:
        payload = payload_from_version(db, row)
    errors = validate_rules_dict(payload)
    return {"valid": not errors, "errors": errors}


@router.post("/versions/{version_id}/activate", response_model=VersionOut)
def activate(
    version_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionOut:
    row = _version(db, version_id)
    payload = payload_from_version(db, row)
    errors = validate_rules_dict(payload)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors[:5]))
    try:
        activate_version(db, row, user_id=admin.id)
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _version_out(db, row)


@router.post("/versions/{version_id}/rollback", response_model=VersionOut)
def rollback(
    version_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionOut:
    source = _version(db, version_id)
    if source.status == "active":
        raise HTTPException(status_code=409, detail="该版本已是当前 active 版本")
    payload = payload_from_version(db, source)
    current = get_active_version(db)
    base_version = current.version if current else source.version
    version = next_version(db, base_version)
    try:
        row = create_version(
            db,
            payload,
            status="active",
            version=version,
            note=f"回滚自 {source.version}",
            user_id=admin.id,
        )
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _version_out(db, row)


@router.get("/versions/{version_id}/export")
def export_version(
    version_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    row = _version(db, version_id)
    content = export_yaml(payload_from_version(db, row))
    filename = f"rules-{row.version}.yaml"
    return Response(
        content=content.encode("utf-8"),
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=VersionDetailOut, status_code=201)
def import_rules(
    data: ImportIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> VersionDetailOut:
    try:
        payload = parse_rules_text(data.yaml)
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not payload.get("global"):
        active = get_active_version(db)
        if active:
            payload["global"] = payload_from_version(db, active).get("global") or {}
    current = get_active_version(db)
    base_version = current.version if current else str(payload.get("version") or "1.0")
    version = data.version or next_version(db, base_version)
    try:
        row = create_version(
            db,
            payload,
            status="draft",
            version=version,
            note=data.note or "YAML 导入",
            user_id=admin.id,
        )
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    result = payload_from_version(db, row)
    return VersionDetailOut(
        version=_version_out(db, row),
        payload=result,
        yaml=export_yaml(result),
    )


@router.post("/convert")
def convert_content(
    data: ConvertIn,
    _admin: User = Depends(require_admin),
) -> dict:
    payload = _parse_content(data.content, data.format)
    if data.format == "json":
        return {"format": "yaml", "content": export_yaml(payload)}
    return {"format": "json", "content": json.dumps(payload, ensure_ascii=False, indent=2)}


@router.post("/test")
def test_text(
    data: TestIn,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    if data.version_id:
        row = _version(db, data.version_id)
    else:
        row = _active(db)
    ruleset = get_ruleset_for_version(db, row)
    result = run_text_test(ruleset, data.text)
    result["version"] = row.version
    result["version_id"] = row.id
    return result