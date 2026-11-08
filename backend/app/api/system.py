from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.config import PROJECT_ROOT, settings
from app.db.models import FileRecord, User
from app.db.session import get_db
from app.services.runtime_config import (
    clear_mineru_token,
    save_mineru_token,
    token_status,
)

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


class TokenIn(BaseModel):
    token: str


@router.get("/config")
def config(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    active_jobs = db.scalar(
        select(func.count(FileRecord.id)).where(
            FileRecord.status.in_(("pending", "processing"))
        )
    )
    return {
        **token_status(),
        "env_path": str(PROJECT_ROOT / ".env"),
        "supervised": settings.app_supervised,
        "restart_supported": settings.app_supervised,
        "active_jobs": int(active_jobs or 0),
    }


@router.put("/mineru-token")
def save_token(
    data: TokenIn,
    _admin: User = Depends(require_admin),
) -> dict:
    try:
        return save_mineru_token(data.token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/mineru-token")
def clear_token(
    _admin: User = Depends(require_admin),
) -> dict:
    return clear_mineru_token()


@router.post("/restart")
def restart(
    _admin: User = Depends(require_admin),
) -> dict:
    if not settings.app_supervised:
        raise HTTPException(
            status_code=409,
            detail="当前不是由启动脚本运行，无法自动重启。请关闭后重新双击「启动投标脱敏工具.bat」。",
        )

    def _exit() -> None:
        time.sleep(1.0)
        os._exit(75)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True, "restarting": True}