from __future__ import annotations

import logging
import threading
from pathlib import Path

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.models import FileRecord, RedactionBox, RuleVersion, TaskEvent
from app.db.session import SessionLocal
from app.pipeline import run
from app.rules.store import get_active_ruleset, get_ruleset_for_version
from app.services.file_lock import file_lock
from app.services.mineru_client import MineruCancelled
from app.services.redaction_service import regenerate_full
from app.services.storage import redacted_path, report_path

logger = logging.getLogger("bidredact.worker")

_stop = threading.Event()
_thread: threading.Thread | None = None


def queue_position(db, file_id: int, status: str) -> int:
    if status != "pending":
        return 0
    ahead = db.scalar(
        select(func.count(FileRecord.id)).where(
            FileRecord.status == "pending", FileRecord.id < file_id
        )
    )
    return int(ahead or 0)


def _claim_next(db) -> int | None:
    file_id = db.scalar(
        select(FileRecord.id)
        .where(FileRecord.status == "pending")
        .order_by(FileRecord.id)
        .limit(1)
    )
    if file_id is None:
        return None
    record = db.get(FileRecord, file_id)
    if not record:
        return None
    record.status = "processing"
    record.progress = 5
    record.fail_reason = None
    _add_event(db, file_id, "pending", "processing", "worker claimed")
    db.commit()
    return int(file_id)


def _add_event(db, file_id: int, from_status: str | None, to_status: str, message: str | None = None) -> None:
    db.add(TaskEvent(file_id=file_id, from_status=from_status, to_status=to_status, message=message))


def _ruleset_for(db, record: FileRecord):
    if record.rule_version:
        row = db.scalar(
            select(RuleVersion).where(RuleVersion.version == record.rule_version)
        )
        if row:
            return get_ruleset_for_version(db, row)
    return get_active_ruleset(db)


def _cancel_requested(file_id: int) -> bool:
    db = SessionLocal()
    try:
        value = db.scalar(
            select(FileRecord.cancel_requested).where(FileRecord.id == file_id)
        )
        return bool(value)
    finally:
        db.close()


def _set_progress(file_id: int, value: int) -> None:
    db = SessionLocal()
    try:
        record = db.get(FileRecord, file_id)
        if record and record.status == "processing":
            record.progress = max(0, min(99, value))
            db.commit()
    finally:
        db.close()


def _mark_cancelled(db, record: FileRecord, message: str = "任务已终止") -> None:
    previous = record.status
    record.status = "cancelled"
    record.progress = 0
    record.cancel_requested = False
    record.reprocess = False
    record.fail_reason = message
    _add_event(db, record.id, previous, "cancelled", message)


def process_file(file_id: int) -> None:
    with file_lock(file_id):
        db = SessionLocal()
        try:
            record = db.get(FileRecord, file_id)
            if not record:
                return
            if record.status == "cancelled":
                return
            if record.cancel_requested:
                _mark_cancelled(db, record)
                db.commit()
                return

            record.progress = 15
            db.commit()

            if record.reprocess:
                regenerate_full(db, record, message="admin reprocess")
                db.commit()
                return

            out = redacted_path(file_id)
            out.parent.mkdir(parents=True, exist_ok=True)
            last_progress = {"value": 15}

            def _on_progress(done: int, total: int) -> None:
                if total <= 0:
                    return
                value = 60 + int(25 * done / total)
                if value != last_progress["value"]:
                    last_progress["value"] = value
                    _set_progress(file_id, value)

            try:
                report = run(
                    source=Path(record.original_path),
                    output=out,
                    ruleset=_ruleset_for(db, record),
                    mineru_mode="auto",
                    seal_guard=True,
                    report_path=report_path(file_id),
                    should_cancel=lambda: _cancel_requested(file_id),
                    on_progress=_on_progress,
                )
            except MineruCancelled:
                db.rollback()
                record = db.get(FileRecord, file_id)
                if record:
                    _mark_cancelled(db, record)
                    db.commit()
                return

            if _cancel_requested(file_id):
                db.rollback()
                record = db.get(FileRecord, file_id)
                if record:
                    _mark_cancelled(db, record)
                    db.commit()
                return

            record.progress = 85
            db.execute(delete(RedactionBox).where(RedactionBox.file_id == file_id))
            for item in report["boxes"]:
                x0, y0, x1, y1 = item["rect"]
                db.add(
                    RedactionBox(
                        file_id=file_id,
                        page=int(item["page"]) + 1,
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        category=item["category"],
                        rule_id=item.get("rule_id"),
                        mode=item["mode"],
                        source=item["source"],
                        confidence=float(item["confidence"]),
                        state=item["state"],
                        value_hash=item.get("value_hash"),
                    )
                )

            needs_review = bool(report.get("warnings")) or any(
                b["state"] != "redacted" for b in report["boxes"]
            )
            record.page_count = int(report["pages"])
            record.doc_type = report["doc_type"]
            record.rule_version = report["rules_version"]
            record.redacted_path = str(out)
            record.progress = 100
            record.status = "needs_review" if needs_review else "completed"
            record.fail_reason = None
            record.reprocess = False
            record.cancel_requested = False
            _add_event(db, file_id, "processing", record.status, "done")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("process file %s failed", file_id)
            db.rollback()
            record = db.get(FileRecord, file_id)
            if record:
                if _cancel_requested(file_id):
                    _mark_cancelled(db, record)
                else:
                    record.status = "failed"
                    record.progress = 0
                    record.fail_reason = f"{type(exc).__name__}: {exc}"[:500]
                    record.cancel_requested = False
                    _add_event(db, file_id, "processing", "failed", record.fail_reason)
                db.commit()
        finally:
            db.close()

def _loop() -> None:
    while not _stop.is_set():
        db = SessionLocal()
        try:
            file_id = _claim_next(db)
        finally:
            db.close()
        if file_id is None:
            _stop.wait(2.0)
            continue
        process_file(file_id)


def start_worker() -> None:
    global _thread
    if not settings.worker_enabled:
        logger.info("worker disabled")
        return
    if _thread and _thread.is_alive():
        return
    settings.ensure_dirs()
    db = SessionLocal()
    try:
        for record in db.scalars(select(FileRecord).where(FileRecord.status == "processing")):
            if record.cancel_requested:
                record.status = "cancelled"
                record.progress = 0
                record.cancel_requested = False
                record.fail_reason = "任务已终止"
            else:
                record.status = "pending"
                record.progress = 0
        db.commit()
    finally:
        db.close()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="bid-redact-worker", daemon=True)
    _thread.start()
    logger.info("worker started")


def stop_worker() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=5)