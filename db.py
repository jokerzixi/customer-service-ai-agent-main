"""
PostgreSQL 连接与业务表初始化（用户、会话目录、消息镜像）。
LangGraph 生产部署的 Checkpointer 使用同一 DATABASE_URI / DATABASE_URL。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    os.getenv(
        "DATABASE_URI",
        "postgresql://cs_user:cs_pass@127.0.0.1:5432/customer_service",
    ),
)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def db_cursor(dict_cursor: bool = True) -> Iterator[Any]:
    conn = get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor if dict_cursor else None)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL DEFAULT '新对话',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
    ON conversations (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    is_user BOOLEAN NOT NULL DEFAULT TRUE,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conv
    ON conversation_messages (conversation_id, id);
"""


def init_db() -> None:
    """创建业务表（幂等）。"""
    with db_cursor(dict_cursor=False) as cur:
        cur.execute(SCHEMA_SQL)


def ping_db() -> Dict[str, Any]:
    try:
        with db_cursor(dict_cursor=False) as cur:
            cur.execute("SELECT 1")
        return {"ok": True, "database_url_host": _safe_host(DATABASE_URL)}
    except Exception as e:
        return {"ok": False, "error": str(e), "database_url_host": _safe_host(DATABASE_URL)}


def _safe_host(url: str) -> str:
    try:
        # postgresql://user:pass@host:port/db
        after_at = url.split("@", 1)[-1]
        return after_at.split("/", 1)[0]
    except Exception:
        return "(unknown)"
