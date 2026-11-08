r"""开发辅助脚本：验证 SQLite 连接与库状态（只读）。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.check_db
"""
from sqlalchemy import text

from app.db.session import DATABASE_URL, engine


def main() -> None:
    with engine.connect() as conn:
        version = conn.execute(text("SELECT sqlite_version()")).scalar()
        journal = conn.execute(text("PRAGMA journal_mode")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()
        print(f"database={DATABASE_URL}")
        print(f"sqlite_version={version} journal_mode={journal} foreign_keys={foreign_keys}")
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ).fetchall()
        print(f"tables={len(rows)}")
        for (name,) in rows:
            print(f"  - {name}")


if __name__ == "__main__":
    main()