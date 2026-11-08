from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.db.models import FileRecord, RedactionBox, User
from app.db.session import get_db
from app.services.redaction_service import apply_incremental, regenerate_full
from app.schemas import (
    AdminBoxIn,
    AdminBoxUpdate,
    BoxOut,
    FileListOut,
    FileOut,
    ReviewIn,
    StatsOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/files", response_model=FileListOut)
def all_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    owner_id: int | None = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileListOut:
    conditions = []
    if status_filter:
        conditions.append(FileRecord.status == status_filter)
    if owner_id:
        conditions.append(FileRecord.owner_id == owner_id)
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


@router.get("/stats", response_model=StatsOut)
def stats(_admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> StatsOut:
    def count_status(value: str) -> int:
        return int(
            db.scalar(select(func.count(FileRecord.id)).where(FileRecord.status == value)) or 0
        )

    total = int(db.scalar(select(func.count(FileRecord.id))) or 0)
    boxes_total = int(db.scalar(select(func.count(RedactionBox.id))) or 0)
    boxes_pending = int(
        db.scalar(
            select(func.count(RedactionBox.id)).where(RedactionBox.state != "redacted")
        )
        or 0
    )
    by_category_rows = db.execute(
        select(RedactionBox.category, func.count(RedactionBox.id)).group_by(RedactionBox.category)
    ).all()
    return StatsOut(
        total_files=total,
        completed=count_status("completed"),
        needs_review=count_status("needs_review"),
        failed=count_status("failed"),
        cancelled=count_status("cancelled"),
        processing=count_status("processing"),
        pending=count_status("pending"),
        boxes_total=boxes_total,
        boxes_pending=boxes_pending,
        by_category={str(k): int(v) for k, v in by_category_rows},
    )


def _ensure_ready(record: FileRecord) -> None:
    if record.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="文件正在处理中，请稍后再操作")
    if record.status == "cancelled":
        raise HTTPException(status_code=409, detail="文件已终止，请先重新处理")
    if record.status not in ("completed", "needs_review", "failed"):
        raise HTTPException(status_code=409, detail="文件尚未完成首次处理")


def _file(db: Session, file_id: int) -> FileRecord:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    return record


@router.post("/files/{file_id}/boxes", response_model=BoxOut, status_code=201)
def add_box(
    file_id: int,
    data: AdminBoxIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BoxOut:
    record = _file(db, file_id)
    _ensure_ready(record)
    if record.page_count and data.page > record.page_count:
        raise HTTPException(status_code=400, detail="页码超出范围")
    box = RedactionBox(
        file_id=file_id,
        page=data.page,
        x0=data.x0,
        y0=data.y0,
        x1=data.x1,
        y1=data.y1,
        category=data.category,
        rule_id="ADMIN",
        mode=data.mode,
        source="admin",
        confidence=1.0,
        state=data.state,
        created_by=admin.id,
    )
    db.add(box)
    db.flush()
    try:
        apply_incremental(db, record, box)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"重新生成失败: {exc}") from exc
    db.refresh(box)
    return BoxOut.model_validate(box)


@router.patch("/boxes/{box_id}", response_model=BoxOut)
def update_box(
    box_id: int,
    data: AdminBoxUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BoxOut:
    box = db.get(RedactionBox, box_id)
    if not box:
        raise HTTPException(status_code=404, detail="遮蔽框不存在")
    record = _file(db, box.file_id)
    _ensure_ready(record)
    for field in ("page", "x0", "y0", "x1", "y1", "category", "mode", "state"):
        value = getattr(data, field)
        if value is not None:
            setattr(box, field, value)
    if box.x1 <= box.x0 or box.y1 <= box.y0:
        raise HTTPException(status_code=400, detail="坐标范围不合法")
    db.flush()
    try:
        regenerate_full(db, record, message="admin update box")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"重新生成失败: {exc}") from exc
    db.refresh(box)
    return BoxOut.model_validate(box)


@router.delete("/boxes/{box_id}")
def delete_box(
    box_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    box = db.get(RedactionBox, box_id)
    if not box:
        raise HTTPException(status_code=404, detail="遮蔽框不存在")
    record = _file(db, box.file_id)
    _ensure_ready(record)
    count = db.scalar(
        select(func.count(RedactionBox.id)).where(RedactionBox.file_id == record.id)
    )
    if int(count or 0) <= 1:
        raise HTTPException(
            status_code=409,
            detail="这是最后一个遮蔽框，不能忽略；请先新增其他遮蔽框。",
        )
    db.delete(box)
    db.flush()
    try:
        regenerate_full(db, record, message="admin delete box")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"重新生成失败: {exc}") from exc
    return {"ok": True}


@router.post("/files/{file_id}/reprocess", response_model=FileOut)
def reprocess(
    file_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileOut:
    record = _file(db, file_id)
    _ensure_ready(record)
    count = db.scalar(
        select(func.count(RedactionBox.id)).where(RedactionBox.file_id == file_id)
    ) or 0
    if count == 0:
        raise HTTPException(status_code=400, detail="没有可应用的遮蔽框")
    try:
        regenerate_full(db, record, message="admin reprocess")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"重新生成失败: {exc}") from exc
    db.refresh(record)
    return FileOut.model_validate(record)


@router.patch("/files/{file_id}/review", response_model=FileOut)
def review(
    file_id: int,
    data: ReviewIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FileOut:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    record.reviewed_at = datetime.now() if data.reviewed else None
    record.reviewed_by = admin.id if data.reviewed else None
    db.commit()
    db.refresh(record)
    return FileOut.model_validate(record)