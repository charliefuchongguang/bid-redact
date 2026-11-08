r"""管理员增删遮蔽框 + 即时重新生成冒烟测试。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.smoke_admin_boxes
"""
from __future__ import annotations

import time
import uuid

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import PROJECT_ROOT
from app.db.models import FileRecord, RedactionBox, TaskEvent, User
from app.db.session import SessionLocal
from app.main import app
from app.services.storage import original_path, redacted_path

SAMPLE = PROJECT_ROOT / "testdata" / "_probe" / "sample_text_only.pdf"
PHONE = "13800138000"


def wait_ready(client, file_id, headers, timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/files/{file_id}/status", headers=headers)
        r.raise_for_status()
        last = r.json()
        if last["status"] in ("completed", "needs_review", "failed"):
            return last
        time.sleep(2)
    raise SystemExit(f"timeout: {last}")


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    user_id = file_id = None
    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/auth/register",
                json={"username": f"adm_{suffix}", "password": "test123456"},
            )
            r.raise_for_status()
            user_id = r.json()["user"]["id"]
            headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

            with SAMPLE.open("rb") as fh:
                r = client.post(
                    "/api/files",
                    headers=headers,
                    files={"file": (SAMPLE.name, fh, "application/pdf")},
                )
            r.raise_for_status()
            file_id = r.json()["id"]
            print(f"[upload] file={file_id}")
            status = wait_ready(client, file_id, headers)
            print(f"[initial] {status}")
            assert status["status"] in ("completed", "needs_review")

            r = client.post("/api/auth/login", json={"account": "admin", "password": "admin123"})
            r.raise_for_status()
            admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

            boxes = client.get(f"/api/files/{file_id}/boxes", headers=admin).json()
            phone_box = next(b for b in boxes if b["rule_id"] == "RED-03" and b["page"] == 1)
            print(
                f"[box] phone box id={phone_box['id']} "
                f"rect=({phone_box['x0']},{phone_box['y0']},{phone_box['x1']},{phone_box['y1']})"
            )

            r = client.delete(f"/api/admin/boxes/{phone_box['id']}", headers=admin)
            r.raise_for_status()
            status = client.get(f"/api/files/{file_id}/status", headers=headers).json()
            print(f"[after delete] {status}")
            boxes_after = client.get(f"/api/files/{file_id}/boxes", headers=headers).json()
            assert len(boxes_after) == len(boxes) - 1

            pdf = client.get(f"/api/files/{file_id}/download", headers=headers).content
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            text = doc[0].get_text()
            doc.close()
            print(f"[after delete] phone visible={PHONE in text}")
            assert PHONE in text, "删除遮蔽框后原手机号应重新可见"

            payload = {
                "page": 1,
                "x0": phone_box["x0"],
                "y0": phone_box["y0"],
                "x1": phone_box["x1"],
                "y1": phone_box["y1"],
                "category": "personal",
                "mode": "rect",
            }
            r = client.post(f"/api/admin/files/{file_id}/boxes", headers=admin, json=payload)
            r.raise_for_status()
            status = client.get(f"/api/files/{file_id}/status", headers=headers).json()
            print(f"[after add] {status}")
            boxes_final = client.get(f"/api/files/{file_id}/boxes", headers=headers).json()
            assert len(boxes_final) == len(boxes)

            pdf = client.get(f"/api/files/{file_id}/download", headers=headers).content
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            text = doc[0].get_text()
            doc.close()
            print(f"[after add] phone visible={PHONE in text}")
            assert PHONE not in text, "新增遮蔽框后手机号应被遮住"

        print("ADMIN BOX SMOKE OK")
    finally:
        cleanup(file_id, user_id)


def cleanup(file_id, user_id) -> None:
    db = SessionLocal()
    try:
        if file_id:
            db.execute(delete(RedactionBox).where(RedactionBox.file_id == file_id))
            db.execute(delete(TaskEvent).where(TaskEvent.file_id == file_id))
            db.execute(delete(FileRecord).where(FileRecord.id == file_id))
            original_path(file_id).unlink(missing_ok=True)
            redacted_path(file_id).unlink(missing_ok=True)
            (PROJECT_ROOT / "data" / "logs" / f"{file_id}.report.json").unlink(missing_ok=True)
        if user_id:
            db.execute(delete(User).where(User.id == user_id))
        db.commit()
        print("[cleanup] done")
    finally:
        db.close()


if __name__ == "__main__":
    main()