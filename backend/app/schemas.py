from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class RegisterIn(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=64)
    email: str | None = None

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        if not USERNAME_RE.fullmatch(v):
            raise ValueError("用户名需为 3-32 位字母、数字、下划线、点或短横线")
        return v

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        if v and not EMAIL_RE.fullmatch(v):
            raise ValueError("邮箱格式不正确")
        return v


class LoginIn(BaseModel):
    account: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str | None
    email: str | None
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class BoxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    category: str
    rule_id: str | None
    mode: str
    source: str
    confidence: float
    state: str
    value_hash: str | None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    original_name: str
    status: str
    progress: int
    page_count: int
    doc_type: str | None
    rule_version: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FileStatusOut(BaseModel):
    id: int
    status: str
    progress: int
    queue_position: int
    fail_reason: str | None
    box_count: int
    redacted_ready: bool


class FileListOut(BaseModel):
    items: list[FileOut]
    total: int
    page: int
    page_size: int


class AdminBoxIn(BaseModel):
    page: int = Field(ge=1)
    x0: float
    y0: float
    x1: float
    y1: float
    category: str = "personal"
    mode: str = "rect"
    state: str = "redacted"

    @field_validator("x1")
    @classmethod
    def check_x(cls, v: float, info):
        if v <= info.data.get("x0", 0):
            raise ValueError("x1 必须大于 x0")
        return v

    @field_validator("y1")
    @classmethod
    def check_y(cls, v: float, info):
        if v <= info.data.get("y0", 0):
            raise ValueError("y1 必须大于 y0")
        return v

    @field_validator("category")
    @classmethod
    def check_category(cls, v: str) -> str:
        if v not in ("personal", "secret", "contact"):
            raise ValueError("category 不合法")
        return v

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ("rect", "card", "image", "cell"):
            raise ValueError("mode 不合法")
        return v


class AdminBoxUpdate(BaseModel):
    page: int | None = Field(default=None, ge=1)
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    category: str | None = None
    mode: str | None = None
    state: str | None = None


class PageSizeOut(BaseModel):
    page: int
    width: float
    height: float


class PageMetaOut(BaseModel):
    page_count: int
    pages: list[PageSizeOut]


class ReviewIn(BaseModel):
    reviewed: bool = True


class StatsOut(BaseModel):
    total_files: int
    completed: int
    needs_review: int
    failed: int
    cancelled: int = 0
    processing: int
    pending: int
    boxes_total: int
    boxes_pending: int
    by_category: dict[str, int]