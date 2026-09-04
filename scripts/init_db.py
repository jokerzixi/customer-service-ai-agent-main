#!/usr/bin/env python3
"""初始化 Postgres 业务表。用法: python scripts/init_db.py"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from db import init_db, ping_db  # noqa: E402


def main():
    status = ping_db()
    if not status.get("ok"):
        print("❌ 无法连接 Postgres:", status)
        print("请先: docker compose up -d postgres")
        sys.exit(1)
    init_db()
    print("✅ 业务表初始化完成")


if __name__ == "__main__":
    main()
