#!/usr/bin/env python3
"""
多智能体客服系统 - Web 入口
Flask + Redis Session 登录态；Postgres 用户/会话目录；LangGraph 对话编排。
"""

from __future__ import annotations

import os
import time
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

import redis
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session

load_dotenv()

from auth_service import authenticate_user, create_user, get_user_by_id
from chat_web_service import (
    clear_thread_and_create_new,
    create_langgraph_thread,
    delete_remote_thread,
    fetch_thread_conversation_history,
    langgraph_connectivity_test,
    run_chat_sync,
    stream_chat_events,
)
from conversation_store import (
    delete_conversation,
    ensure_conversation,
    get_conversation_for_user,
    get_messages,
    list_conversations,
    rebind_conversation_thread,
    sync_from_history,
)
from db import init_db, ping_db
from config import *  # noqa: E402,F401,F403

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Flask + Redis Session
# ---------------------------------------------------------------------------
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key-here")
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
# 本机 Redis 3.x 不支持 RESP3 HELLO，强制 protocol=2
app.config.update(
    SESSION_TYPE="redis",
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,
    SESSION_KEY_PREFIX="cs_sess:",
    SESSION_REDIS=redis.from_url(REDIS_URL, protocol=2),
    PERMANENT_SESSION_LIFETIME=int(os.getenv("SESSION_TTL_SECONDS", "86400")),
)
Session(app)


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "未登录", "code": "unauthorized"}), 401
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)

    return wrapped


def current_user_id() -> int:
    return int(session["user_id"])


def _sync_thread_memory(user_id: int, thread_id: str, title_hint: Optional[str] = None) -> None:
    history = fetch_thread_conversation_history(thread_id)
    if history:
        sync_from_history(user_id, thread_id, history, title_hint=title_hint)
    else:
        ensure_conversation(user_id, thread_id, title=title_hint or "新对话")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/")
@login_required
def index():
    user = get_user_by_id(current_user_id())
    return render_template("index.html", current_user=user)


# ---------------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    user, err = create_user(data.get("username", ""), data.get("password", ""))
    if err:
        return jsonify({"error": err}), 400
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"user": user, "message": "注册成功"})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    user, err = authenticate_user(data.get("username", ""), data.get("password", ""))
    if err:
        return jsonify({"error": err}), 401
    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"user": user, "message": "登录成功"})


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"message": "已退出登录"})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"authenticated": False}), 401
    user = get_user_by_id(int(uid))
    if not user:
        session.clear()
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user})


# ---------------------------------------------------------------------------
# Chat / Sessions（需登录，按用户隔离）
# ---------------------------------------------------------------------------

@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    try:
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()
        client_session_id = data.get("session_id")
        uid = current_user_id()

        sid = str(client_session_id) if client_session_id else ""
        if sid and not sid.startswith("web_"):
            owned = get_conversation_for_user(uid, sid)
            if not owned:
                return jsonify({"error": "会话不存在或无权访问"}), 403
        else:
            # 占位 id：交给后端新建 thread
            client_session_id = None

        ai_text, err_msg, http_code, thread_id = run_chat_sync(user_message, client_session_id)
        if err_msg:
            return jsonify({"error": err_msg}), http_code or 500

        assert thread_id
        # 归属校验：若库中已有且非本人则拒绝写库
        existing = get_conversation_for_user(uid, thread_id)
        if existing is None:
            # 确认没被其他用户占用
            try:
                ensure_conversation(uid, thread_id, title=user_message[:80] or "新对话")
            except PermissionError:
                return jsonify({"error": "无权使用该会话"}), 403

        _sync_thread_memory(uid, thread_id, title_hint=user_message[:80])

        return jsonify({
            "response": ai_text,
            "session_id": thread_id,
            "thread_id": thread_id,
        })
    except Exception as e:
        print(f"❌ 聊天处理错误: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"内部错误: {str(e)}"}), 500


@app.route("/api/chat/stream", methods=["POST"])
@login_required
def chat_stream():
    try:
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()
        client_session_id = data.get("session_id")
        uid = current_user_id()

        sid = str(client_session_id) if client_session_id else ""
        if sid and not sid.startswith("web_"):
            owned = get_conversation_for_user(uid, sid)
            if not owned:
                return jsonify({"error": "会话不存在或无权访问"}), 403
        else:
            client_session_id = None

        def generate():
            last_tid = None
            for chunk in stream_chat_events(user_message, client_session_id):
                if '"thread_id"' in chunk or '"session_id"' in chunk:
                    try:
                        import json as _json
                        line = chunk.strip()
                        if line.startswith("data: ") and not line.endswith("[DONE]"):
                            payload = _json.loads(line[6:])
                            last_tid = payload.get("thread_id") or payload.get("session_id")
                    except Exception:
                        pass
                yield chunk
            if last_tid:
                try:
                    ensure_conversation(uid, last_tid, title=user_message[:80] or "新对话")
                    _sync_thread_memory(uid, last_tid, title_hint=user_message[:80])
                except Exception as e:
                    print(f"⚠️ 流式结束后同步会话失败: {e}")

        return Response(generate(), mimetype="text/event-stream")
    except Exception as e:
        print(f"❌ 流式聊天处理错误: {e}")
        return jsonify({"error": f"内部错误: {str(e)}"}), 500


@app.route("/api/sessions", methods=["GET"])
@login_required
def get_sessions():
    try:
        sessions = list_conversations(current_user_id())
        return jsonify({"sessions": sessions})
    except Exception as e:
        return jsonify({"error": f"获取会话列表失败: {e}"}), 500


@app.route("/api/sessions/<session_id>", methods=["GET"])
@login_required
def get_session(session_id):
    uid = current_user_id()
    conv = get_conversation_for_user(uid, session_id)
    if not conv:
        return jsonify({"error": "会话不存在或无权访问"}), 404

    history = get_messages(int(conv["id"]))
    if not history:
        # 回退 LangGraph state 并镜像入库
        history = fetch_thread_conversation_history(session_id)
        if history:
            sync_from_history(uid, session_id, history)

    return jsonify({
        "session": {
            "session_id": session_id,
            "created_at": conv["created_at"].timestamp() if hasattr(conv["created_at"], "timestamp") else time.time(),
            "conversation_history": history,
        }
    })


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    uid = current_user_id()
    conv = get_conversation_for_user(uid, session_id)
    if not conv:
        return jsonify({"error": "会话不存在或无权访问"}), 404

    try:
        delete_remote_thread(session_id)
    except Exception as e:
        print(f"⚠️ 删除远程线程失败（继续删本地）: {e}")

    delete_conversation(uid, session_id)
    return jsonify({"message": "会话删除成功"})


@app.route("/api/sessions/<session_id>/clear", methods=["POST"])
@login_required
def clear_session(session_id):
    uid = current_user_id()
    conv = get_conversation_for_user(uid, session_id)
    if not conv:
        return jsonify({"error": "会话不存在或无权访问"}), 404

    new_thread_id, err = clear_thread_and_create_new(session_id)
    if err:
        return jsonify({"error": err}), 500

    rebind_conversation_thread(uid, session_id, new_thread_id)
    return jsonify({"message": "会话清空成功", "new_thread_id": new_thread_id})


@app.route("/api/new_session", methods=["POST"])
@login_required
def create_new_session():
    uid = current_user_id()
    thread_id = create_langgraph_thread()
    if not thread_id:
        return jsonify({"error": "创建 LangGraph 线程失败"}), 500
    ensure_conversation(uid, thread_id, title="新对话")
    return jsonify({"session_id": thread_id, "thread_id": thread_id, "message": "新会话创建成功"})


@app.route("/api/health")
def health_check():
    db_status = ping_db()
    try:
        app.config["SESSION_REDIS"].ping()
        redis_ok = True
    except Exception as e:
        redis_ok = False
        db_status["redis_error"] = str(e)
    return jsonify({
        "status": "healthy" if db_status.get("ok") and redis_ok else "degraded",
        "timestamp": time.time(),
        "postgres": db_status,
        "redis": {"ok": redis_ok, "url": REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL},
    })


@app.route("/api/test")
@login_required
def test_langgraph():
    result, err = langgraph_connectivity_test()
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result)


def main():
    print("🚀 多智能体客服系统 Web 应用")
    print("=" * 60)
    try:
        init_db()
        print("✅ Postgres 业务表已就绪")
    except Exception as e:
        print(f"❌ Postgres 初始化失败: {e}")
        print("   请先启动 Postgres（见 docker-compose.yml），并检查 DATABASE_URL")
    print(f"🔐 Redis Session: {REDIS_URL}")
    print("🌐 启动 Web 服务...")
    print("📱 访问地址: http://localhost:5000/login")
    print()
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
