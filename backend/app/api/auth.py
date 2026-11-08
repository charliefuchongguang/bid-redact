from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, get_current_user
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED = 5
LOCK_MINUTES = 15


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if data.email and db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="邮箱已存在")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        role="admin" if settings.local_full_access else "user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(
        select(User).where(or_(User.username == data.account, User.email == data.account))
    )
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    now = datetime.now()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=423, detail="尝试次数过多，账号已临时锁定")

    if not verify_password(data.password, user.password_hash):
        user.failed_count += 1
        if user.failed_count >= MAX_FAILED:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_count = 0
        db.commit()
        raise HTTPException(status_code=401, detail="账号或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    user.failed_count = 0
    user.locked_until = None
    if settings.local_full_access and user.role != "admin":
        user.role = "admin"
    db.commit()
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)