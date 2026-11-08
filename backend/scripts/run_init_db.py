r"""初始化数据库：建表 + 种子管理员。

用法（在 backend 目录）：
    ..\.venv\Scripts\python.exe -m app.db.init_db
"""
from app.db.init_db import init_db

if __name__ == "__main__":
    init_db()