"""
用户会话目录与对话消息镜像（Postgres）。
登录后按 user_id 读取历史；正文以本表为准（兼容 langgraph dev 内存 Checkpointer）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import db_cursor


def ensure_conversation(user_id: int, thread_id: str, title: str = "新对话") -> Dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, thread_id, title, created_at, updated_at
            FROM conversations
            WHERE thread_id = %s
            """,
            (thread_id,),
        )
        existing = cur.fetchone()
        if existing:
            if int(existing["user_id"]) != int(user_id):
                raise PermissionError("该会话不属于当前用户")
            cur.execute(
                """
                UPDATE conversations
                SET updated_at = NOW()
                WHERE id = %s
                RETURNING id, user_id, thread_id, title, created_at, updated_at
                """,
                (existing["id"],),
            )
            return _conv_row(cur.fetchone())

        cur.execute(
            """
            INSERT INTO conversations (user_id, thread_id, title)
            VALUES (%s, %s, %s)
            RETURNING id, user_id, thread_id, title, created_at, updated_at
            """,
            (user_id, thread_id, (title or "新对话")[:255]),
        )
        return _conv_row(cur.fetchone())


def get_conversation_for_user(user_id: int, thread_id: str) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, thread_id, title, created_at, updated_at
            FROM conversations
            WHERE thread_id = %s AND user_id = %s
            """,
            (thread_id, user_id),
        )
        row = cur.fetchone()
    return _conv_row(row) if row else None


def list_conversations(user_id: int) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                c.id,
                c.user_id,
                c.thread_id,
                c.title,
                c.created_at,
                c.updated_at,
                COALESCE(
                    (SELECT COUNT(*) FROM conversation_messages m WHERE m.conversation_id = c.id),
                    0
                ) AS message_count,
                COALESCE(
                    (
                        SELECT m.content FROM conversation_messages m
                        WHERE m.conversation_id = c.id AND m.is_user = TRUE
                        ORDER BY m.id DESC LIMIT 1
                    ),
                    ''
                ) AS last_user_question
            FROM conversations c
            WHERE c.user_id = %s
            ORDER BY c.updated_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall() or []

    sessions: List[Dict[str, Any]] = []
    for row in rows:
        created = row["created_at"]
        sessions.append({
            "session_id": row["thread_id"],
            "thread_id": row["thread_id"],
            "title": row["title"],
            "created_at": created.timestamp() if isinstance(created, datetime) else float(created or 0),
            "updated_at": row["updated_at"].timestamp() if isinstance(row["updated_at"], datetime) else None,
            "message_count": int(row["message_count"] or 0),
            "last_user_question": (row["last_user_question"] or "").strip(),
        })
    return sessions


def replace_messages(conversation_id: int, turns: List[Dict[str, Any]]) -> None:
    """用完整轮次列表覆盖该会话消息（与 LangGraph state 同步）。"""
    with db_cursor() as cur:
        cur.execute("DELETE FROM conversation_messages WHERE conversation_id = %s", (conversation_id,))
        for turn in turns:
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            is_user = bool(turn.get("is_user", turn.get("role") == "user"))
            role = turn.get("role") or ("user" if is_user else "assistant")
            cur.execute(
                """
                INSERT INTO conversation_messages (conversation_id, is_user, role, content)
                VALUES (%s, %s, %s, %s)
                """,
                (conversation_id, is_user, role, content),
            )
        # 更新标题与时间
        title = "新对话"
        for turn in reversed(turns):
            if turn.get("is_user") or turn.get("role") == "user":
                t = (turn.get("content") or "").strip()
                if t:
                    title = t[:80]
                    break
        cur.execute(
            """
            UPDATE conversations
            SET title = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (title, conversation_id),
        )


def get_messages(conversation_id: int) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT is_user, role, content, created_at
            FROM conversation_messages
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        rows = cur.fetchall() or []

    history: List[Dict[str, Any]] = []
    for row in rows:
        ts = row["created_at"]
        entry: Dict[str, Any] = {
            "is_user": bool(row["is_user"]),
            "role": row["role"] or ("user" if row["is_user"] else "assistant"),
            "content": row["content"],
        }
        if ts:
            entry["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else str(ts)
        history.append(entry)
    return history


def delete_conversation(user_id: int, thread_id: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM conversations WHERE user_id = %s AND thread_id = %s RETURNING id",
            (user_id, thread_id),
        )
        return cur.fetchone() is not None


def rebind_conversation_thread(user_id: int, old_thread_id: str, new_thread_id: str) -> Optional[Dict[str, Any]]:
    """清空会话：保留目录记录，换绑新 thread，并清空消息。"""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id FROM conversations
            WHERE user_id = %s AND thread_id = %s
            """,
            (user_id, old_thread_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        conv_id = row["id"]
        cur.execute("DELETE FROM conversation_messages WHERE conversation_id = %s", (conv_id,))
        cur.execute(
            """
            UPDATE conversations
            SET thread_id = %s, title = '新对话', updated_at = NOW()
            WHERE id = %s
            RETURNING id, user_id, thread_id, title, created_at, updated_at
            """,
            (new_thread_id, conv_id),
        )
        updated = cur.fetchone()
    return _conv_row(updated) if updated else None


def sync_from_history(
    user_id: int,
    thread_id: str,
    conversation_history: List[Dict[str, Any]],
    title_hint: Optional[str] = None,
) -> Dict[str, Any]:
    conv = ensure_conversation(user_id, thread_id, title=title_hint or "新对话")
    replace_messages(int(conv["id"]), conversation_history or [])
    return get_conversation_for_user(user_id, thread_id) or conv


def _conv_row(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "thread_id": row["thread_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
