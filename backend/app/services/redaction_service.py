from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FileRecord, RedactionBox, RuleVersion, TaskEvent
from app.redactor.redactor import redact_document
from app.rules.box import Box
from app.rules.store import get_active_ruleset, get_ruleset_for_version
from app.services.file_lock import file_lock
from app.services.storage import original_path, redacted_path

NO_BOX_REASON = "当前没有可应用的遮蔽框，已保留上一次脱敏件"


def row_to_box(row: RedactionBox) -> Box:
    return Box(
        page=max(row.page - 1, 0),
        rect=pymupdf.Rect(row.x0, row.y0, row.x1, row.y1),
        category=row.category,
        rule_id=row.rule_id or "ADMIN",
        mode=row.mode,
        source=row.source,
        confidence=row.confidence,
        value="",
        state=row.state,
    )


def boxes_for_file(db: Session, file_id: int) -> list[RedactionBox]:
    return list(
        db.scalars(
            select(RedactionBox)
            .where(RedactionBox.file_id == file_id)
            .order_by(RedactionBox.page, RedactionBox.y0, RedactionBox.x0)
        )
    )


def _ruleset_for_record(db: Session, record: FileRecord):
    if record.rule_version:
        row = db.scalar(
            select(RuleVersion).where(RuleVersion.version == record.rule_version)
        )
        if row:
            return get_ruleset_for_version(db, row)
    return get_active_ruleset(db)


def _source_for(record: FileRecord) -> Path:
    path = Path(record.original_path) if record.original_path else original_path(record.id)
    if not path.exists():
        path = original_path(record.id)
    if not path.exists():
        raise FileNotFoundError(f"原文件不存在: {path}")
    return path


def _tmp_path(out: Path) -> Path:
    return out.parent / f"{out.stem}.tmp-{os.getpid()}-{threading.get_ident()}.pdf"


def _replace(src: Path, dest: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if attempt >= 4:
                raise
            time.sleep(0.1)


def _finalize(
    db: Session,
    record: FileRecord,
    rows: list[RedactionBox],
    *,
    message: str,
    needs_review: bool,
) -> str:
    status = "needs_review" if needs_review else "completed"
    previous = record.status
    record.status = status
    record.progress = 100
    record.fail_reason = None
    record.redacted_path = str(redacted_path(record.id))
    record.reviewed_at = None
    record.reviewed_by = None
    db.add(TaskEvent(file_id=record.id, from_status=previous, to_status=status, message=message))
    return status


def regenerate_full(db: Session, record: FileRecord, *, message: str = "admin reprocess") -> str:
    """从原 PDF 全量重建脱敏件（不调用 MinerU）。"""
    with file_lock(record.id):
        rows = boxes_for_file(db, record.id)
        if not rows:
            previous = record.status
            record.status = "needs_review"
            record.progress = 100
            record.reprocess = False
            record.fail_reason = NO_BOX_REASON
            db.add(
                TaskEvent(
                    file_id=record.id,
                    from_status=previous,
                    to_status="needs_review",
                    message=message,
                )
            )
            return "needs_review"

        ruleset = _ruleset_for_record(db, record)
        boxes = [row_to_box(row) for row in rows]
        out = redacted_path(record.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = _tmp_path(out)
        try:
            redact_document(
                source=_source_for(record),
                output=tmp,
                boxes=boxes,
                ruleset=ruleset,
                apply_seal_guard=True,
            )
            _replace(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)

        for row, box in zip(rows, boxes):
            row.state = box.state
        needs_review = any(box.state != "redacted" for box in boxes)
        record.reprocess = False
        return _finalize(db, record, rows, message=message, needs_review=needs_review)


def apply_incremental(db: Session, record: FileRecord, new_row: RedactionBox) -> str:
    """在现有脱敏件上增量应用一个新遮蔽框，失败时回退全量重建。"""
    with file_lock(record.id):
        out = redacted_path(record.id)
        if not out.exists():
            return regenerate_full(db, record, message="admin add box fallback")

        box = row_to_box(new_row)
        ruleset = _ruleset_for_record(db, record)
        tmp = _tmp_path(out)
        try:
            redact_document(
                source=out,
                output=tmp,
                boxes=[box],
                ruleset=ruleset,
                apply_seal_guard=True,
            )
            _replace(tmp, out)
        except Exception:
            tmp.unlink(missing_ok=True)
            return regenerate_full(db, record, message="admin add box fallback")

        new_row.state = box.state
        rows = boxes_for_file(db, record.id)
        needs_review = any(row.state != "redacted" for row in rows)
        record.reprocess = False
        return _finalize(db, record, rows, message="admin add box", needs_review=needs_review)