from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.db.models import FileRecord, RedactionBox, TaskEvent, User
from app.db.session import get_db
from app.rules.store import get_active_version, seed_rules_if_empty
from app.schemas import BoxOut, FileListOut, FileOut, FileStatusOut, PageMetaOut, PageSizeOut
from app.services.storage import original_path, redacted_path, save_upload
from app.services.worker import queue_position

router = APIRouter(prefix="/files", tags=["files"])


def _access(db: Session, file_id: int, user: User) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    if record.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该文件")
    return record


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileOut:
    name = Path(file.filename or "upload.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    active_rules = get_active_version(db)
    if active_rules is None:
        active_rules = seed_rules_if_empty(db)

    record = FileRecord(
        owner_id=user.id,
        original_name=name,
        original_path="",
        sha256="",
        status="pending",
        progress=0,
        rule_version=active_rules.version if active_rules else None,
    )
    db.add(record)
    db.flush()

    try:
        path, _size, sha = save_upload(file.file, record.id, settings.max_upload_bytes)
    except ValueError:
        db.rollback()
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb}MB 限制")

    try:
        doc = pymupdf.open(path)
        encrypted = bool(doc.needs_pass or doc.is_encrypted)
        pages = len(doc)
        doc.close()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文件损坏或不是有效的 PDF")

    if encrypted:
        db.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="加密 PDF 无法处理")

    record.original_path = str(path)
    record.sha256 = sha
    record.page_count = pages
    db.add(TaskEvent(file_id=record.id, to_status="pending", message="uploaded"))
    db.commit()
    db.refresh(record)
    return FileOut.model_validate(record)


@router.get("", response_model=FileListOut)
def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileListOut:
    conditions = [FileRecord.owner_id == user.id]
    if status_filter:
        conditions.append(FileRecord.status == status_filter)
    total = db.scalar(select(func.count(FileRecord.id)).where(*conditions)) or 0
    rows = db.scalars(
        select(FileRecord)
        .where(*conditions)
        .order_by(FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return FileListOut(
        items=[FileOut.model_validate(r) for r in rows],
        total=int(total),
        page=page,
        page_size=page_size,
    )


@router.get("/{file_id}", response_model=FileOut)
def detail(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileOut:
    return FileOut.model_validate(_access(db, file_id, user))


@router.get("/{file_id}/status", response_model=FileStatusOut)
def file_status(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileStatusOut:
    record = _access(db, file_id, user)
    box_count = db.scalar(
        select(func.count(RedactionBox.id)).where(RedactionBox.file_id == file_id)
    ) or 0
    return FileStatusOut(
        id=record.id,
        status=record.status,
        progress=record.progress,
        queue_position=queue_position(db, record.id, record.status),
        fail_reason=record.fail_reason,
        box_count=int(box_count),
        redacted_ready=bool(record.redacted_path and Path(record.redacted_path).exists()),
    )


@router.get("/{file_id}/boxes", response_model=list[BoxOut])
def boxes(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BoxOut]:
    _access(db, file_id, user)
    rows = db.scalars(
        select(RedactionBox)
        .where(RedactionBox.file_id == file_id)
        .order_by(RedactionBox.page, RedactionBox.y0, RedactionBox.x0)
    ).all()
    return [BoxOut.model_validate(r) for r in rows]


@router.get("/{file_id}/download")
def download(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    record = _access(db, file_id, user)
    if record.status not in ("completed", "needs_review") or not record.redacted_path:
        raise HTTPException(status_code=409, detail="脱敏件尚未生成")
    path = Path(record.redacted_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="脱敏件不存在")
    stem = Path(record.original_name).stem
    return FileResponse(path, media_type="application/pdf", filename=f"{stem}_已脱敏.pdf")


@router.get("/{file_id}/page-meta", response_model=PageMetaOut)
def page_meta(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PageMetaOut:
    record = _access(db, file_id, user)
    path = Path(record.redacted_path) if record.redacted_path else original_path(file_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    doc = pymupdf.open(path)
    try:
        pages = [
            PageSizeOut(page=i + 1, width=page.rect.width, height=page.rect.height)
            for i, page in enumerate(doc)
        ]
    finally:
        doc.close()
    return PageMetaOut(page_count=len(pages), pages=pages)


@router.get("/{file_id}/preview/{page}")
def preview(
    file_id: int,
    page: int,
    dpi: int = Query(110, ge=72, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    record = _access(db, file_id, user)
    if page < 1 or (record.page_count and page > record.page_count):
        raise HTTPException(status_code=400, detail="页码超出范围")

    path = Path(record.redacted_path) if record.redacted_path else original_path(file_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    doc = pymupdf.open(path)
    try:
        pix = doc[page - 1].get_pixmap(dpi=dpi)
        data = pix.tobytes("png")
    finally:
        doc.close()
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/{file_id}/cancel", response_model=FileOut)
def cancel(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileOut:
    record = _access(db, file_id, user)
    if record.status not in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="当前状态不可终止")
    previous = record.status
    if record.status == "pending":
        record.status = "cancelled"
        record.progress = 0
        record.fail_reason = "任务已终止"
        record.cancel_requested = False
        db.add(TaskEvent(file_id=record.id, from_status=previous, to_status="cancelled", message="cancelled"))
    else:
        record.cancel_requested = True
        db.add(
            TaskEvent(
                file_id=record.id,
                from_status=previous,
                to_status="processing",
                message="cancel requested",
            )
        )
    db.commit()
    db.refresh(record)
    return FileOut.model_validate(record)


@router.post("/{file_id}/retry", response_model=FileOut)
def retry(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileOut:
    record = _access(db, file_id, user)
    if record.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="文件已在队列中")
    previous = record.status
    active = get_active_version(db)
    record.status = "pending"
    record.progress = 0
    record.fail_reason = None
    if active:
        record.rule_version = active.version
    db.add(TaskEvent(file_id=record.id, from_status=previous, to_status="pending", message="retry"))
    db.commit()
    db.refresh(record)
    return FileOut.model_validate(record)