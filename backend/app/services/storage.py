from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.core.config import settings


def original_path(file_id: int) -> Path:
    return settings.data_dir / "original" / f"{file_id}.pdf"


def redacted_path(file_id: int) -> Path:
    return settings.data_dir / "redacted" / f"{file_id}.pdf"


def report_path(file_id: int) -> Path:
    return settings.data_dir / "logs" / f"{file_id}.report.json"


def save_upload(stream, file_id: int, max_bytes: int) -> tuple[Path, int, str]:
    """把上传流写入磁盘，返回 (路径, 字节数, sha256)。超限时清理并抛 ValueError。"""
    settings.ensure_dirs()
    dest = original_path(file_id)
    hasher = hashlib.sha256()
    size = 0
    tmp = dest.with_suffix(".part")
    with tmp.open("wb") as fh:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                fh.close()
                tmp.unlink(missing_ok=True)
                raise ValueError("文件超过大小限制")
            hasher.update(chunk)
            fh.write(chunk)
    tmp.replace(dest)
    return dest, size, hasher.hexdigest()


def remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)


def copy_to(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)