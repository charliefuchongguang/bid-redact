r"""重新处理指定文件，用于补跑新规则/人脸检测。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.reprocess_faces 1 4
    ..\.venv\Scripts\python.exe -m scripts.reprocess_faces --all
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db.models import FileRecord
from app.db.session import SessionLocal
from app.services.worker import process_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*", type=int)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not args.ids and not args.all:
        parser.error("请指定文件 ID，或使用 --all")

    db = SessionLocal()
    try:
        if args.all:
            ids = list(db.scalars(select(FileRecord.id).order_by(FileRecord.id)))
        else:
            ids = args.ids
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if record:
                record.rule_version = None
                record.reprocess = False
                record.cancel_requested = False
        db.commit()
    finally:
        db.close()

    for file_id in ids:
        print(f"processing {file_id}", flush=True)
        process_file(file_id)

    db = SessionLocal()
    try:
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if record:
                print(file_id, record.status, record.page_count, (record.fail_reason or "")[:120])
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())