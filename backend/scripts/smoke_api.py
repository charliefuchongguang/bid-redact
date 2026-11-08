r"""M3 接口冒烟测试：注册 -> 登录 -> 上传 -> 轮询 -> 下载 -> 管理员统计。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.smoke_api
"""
from __future__ import annotations

import time
import uuid

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import PROJECT_ROOT
from app.db.models import FileRecord, RedactionBox, TaskEvent, User
from app.db.session import SessionLocal
from app.main import app
from app.services.storage import original_path, redacted_path

SAMPLE = PROJECT_ROOT / "testdata" / "_probe" / "sample_text_only.pdf"


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"apitest_{suffix}"
    password = "test123456"
    created_user_id: int | None = None
    created_file_id: int | None = None

    try:
        with TestClient(app) as client:
            r = client.post(
                "/api/auth/register",
                json={"username": username, "password": password, "email": f"{username}@example.com"},
            )
            r.raise_for_status()
            data = r.json()
            token = data["access_token"]
            created_user_id = data["user"]["id"]
            headers = {"Authorization": f"Bearer {token}"}
            print(f"[register] user={username} id={created_user_id}")

            with SAMPLE.open("rb") as fh:
                r = client.post(
                    "/api/files",
                    headers=headers,
                    files={"file": (SAMPLE.name, fh, "application/pdf")},
                )
            if r.status_code >= 400:
                raise SystemExit(f"upload failed: {r.status_code} {r.text}")
            created_file_id = r.json()["id"]
            print(f"[upload] file_id={created_file_id}")

            deadline = time.time() + 180
            last = None
            while time.time() < deadline:
                r = client.get(f"/api/files/{created_file_id}/status", headers=headers)
                r.raise_for_status()
                last = r.json()
                print(f"[status] {last}")
                if last["status"] in ("completed", "needs_review", "failed"):
                    break
                time.sleep(2)

            if not last or last["status"] not in ("completed", "needs_review"):
                raise SystemExit(f"file not ready: {last}")

            r = client.get(f"/api/files/{created_file_id}/boxes", headers=headers)
            r.raise_for_status()
            boxes = r.json()
            print(f"[boxes] {len(boxes)}")

            r = client.get(f"/api/files/{created_file_id}/download", headers=headers)
            r.raise_for_status()
            out_doc = pymupdf.open(stream=r.content, filetype="pdf")
            text = out_doc[0].get_text()
            out_doc.close()
            print(f"[download] bytes={len(r.content)} phone_removed={'13800138000' not in text}")
            assert "13800138000" not in text

            r = client.get(f"/api/files/{created_file_id}/preview/1", headers=headers)
            r.raise_for_status()
            print(f"[preview] {r.headers.get('content-type')} bytes={len(r.content)}")

            r = client.post(
                "/api/auth/login",
                json={"account": "admin", "password": "admin123"},
            )
            r.raise_for_status()
            admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = client.get("/api/admin/stats", headers=admin_headers)
            r.raise_for_status()
            print(f"[admin stats] {r.json()}")

            r = client.patch(
                f"/api/admin/files/{created_file_id}/review",
                headers=admin_headers,
                json={"reviewed": True},
            )
            r.raise_for_status()
            print(f"[admin review] reviewed_at={r.json()['reviewed_at']}")

        print("SMOKE OK")
    finally:
        cleanup(created_file_id, created_user_id)


def cleanup(file_id: int | None, user_id: int | None) -> None:
    db = SessionLocal()
    try:
        file_ids: set[int] = set()
        if file_id:
            file_ids.add(file_id)
        if user_id:
            for row in db.scalars(select(FileRecord).where(FileRecord.owner_id == user_id)):
                file_ids.add(row.id)
        for fid in file_ids:
            db.execute(delete(RedactionBox).where(RedactionBox.file_id == fid))
            db.execute(delete(TaskEvent).where(TaskEvent.file_id == fid))
            db.execute(delete(FileRecord).where(FileRecord.id == fid))
            original_path(fid).unlink(missing_ok=True)
            redacted_path(fid).unlink(missing_ok=True)
            (PROJECT_ROOT / "data" / "logs" / f"{fid}.report.json").unlink(missing_ok=True)
        if user_id:
            db.execute(delete(User).where(User.id == user_id))
        db.commit()
        print("[cleanup] done")
    finally:
        db.close()


if __name__ == "__main__":
    main()