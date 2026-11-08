r"""把 rules/rules.yaml 导入并发布为 active 规则版本。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.publish_rules
    ..\.venv\Scripts\python.exe -m scripts.publish_rules --file ..\rules\rules.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.db.init_db import init_db
from app.db.models import RuleVersion
from app.db.session import SessionLocal
from app.rules.loader import payload_sha256, validate_rules_dict
from app.rules.store import activate_version, create_version, save_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        type=Path,
        default=PROJECT_ROOT / "rules" / "rules.yaml",
    )
    parser.add_argument(
        "--update-active",
        action="store_true",
        help="内容变化时原地更新同版本 active 规则（仅开发/联调使用）",
    )
    args = parser.parse_args()

    data = yaml.safe_load(args.file.read_bytes())
    if not isinstance(data, dict):
        raise SystemExit("规则文件根节点必须是对象")
    errors = validate_rules_dict(data)
    if errors:
        raise SystemExit("规则校验失败: " + "; ".join(errors[:8]))
    version = str(data.get("version") or "")
    if not version:
        raise SystemExit("规则文件缺少 version")

    init_db()
    db = SessionLocal()
    try:
        row = db.scalar(select(RuleVersion).where(RuleVersion.version == version))
        if row is None:
            row = create_version(
                db,
                data,
                status="active",
                version=version,
                note=f"从 {args.file.name} 发布",
            )
            db.commit()
            print(f"published {row.version} id={row.id} rules={len(data.get('personal', [])) + len(data.get('secret', [])) + len(data.get('contact', []))}")
            return 0

        if row.status == "active" and row.sha256 == payload_sha256(data):
            print(f"already active {row.version} id={row.id}")
            return 0
        if row.status == "active":
            if not args.update_active:
                raise SystemExit(
                    f"版本 {row.version} 已是 active 且内容不同；请提升 version，"
                    "或开发联调时加 --update-active"
                )
            row.status = "draft"
            db.flush()
        elif row.status != "draft":
            raise SystemExit(
                f"版本 {row.version} 已是 {row.status} 且内容不同；请先提升 rules.yaml 的 version"
            )
        save_payload(db, row, data)
        activate_version(db, row)
        db.commit()
        print(f"activated {row.version} id={row.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())