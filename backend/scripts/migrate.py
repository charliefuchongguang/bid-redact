r"""幂等迁移：为 tm_files 补充新增列（SQLite PRAGMA table_info）。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m scripts.migrate
"""
from sqlalchemy import text

from app.db.session import engine

COLUMNS = {
    "reprocess": "BOOLEAN NOT NULL DEFAULT 0",
    "cancel_requested": "BOOLEAN NOT NULL DEFAULT 0",
}


def main() -> None:
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(tm_files)"))}
        if not existing:
            print("tm_files 不存在，请先运行 app.db.init_db")
            return
        for name, ddl in COLUMNS.items():
            if name in existing:
                print(f"tm_files.{name} already exists")
                continue
            conn.execute(text(f"ALTER TABLE tm_files ADD COLUMN {name} {ddl}"))
            print(f"added tm_files.{name}")


if __name__ == "__main__":
    main()