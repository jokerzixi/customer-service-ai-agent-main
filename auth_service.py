"""
用户注册 / 登录（密码哈希存 Postgres）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from db import db_cursor

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fff]{3,32}$")


def validate_username(username: str) -> Optional[str]:
    if not username or not _USERNAME_RE.match(username.strip()):
        return "用户名需为 3–32 位字母/数字/下划线/中文"
    return None


def validate_password(password: str) -> Optional[str]:
    if not password or len(password) < 6:
        return "密码至少 6 位"
    if len(password) > 128:
        return "密码过长"
    return None


def create_user(username: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    username = (username or "").strip()
    err = validate_username(username) or validate_password(password or "")
    if err:
        return None, err

    password_hash = generate_password_hash(password)
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, password_hash)
                VALUES (%s, %s)
                RETURNING id, username, created_at
                """,
                (username, password_hash),
            )
            row = cur.fetchone()
            return _user_public(row), None
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            return None, "用户名已存在"
        return None, f"注册失败: {msg}"


def authenticate_user(username: str, password: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    username = (username or "").strip()
    if not username or not password:
        return None, "请输入用户名和密码"

    with db_cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()

    if not row or not check_password_hash(row["password_hash"], password):
        return None, "用户名或密码错误"

    return _user_public(row), None


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, username, created_at FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return _user_public(row) if row else None


def _user_public(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
