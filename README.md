<h1 align="center">多智能体客服系统</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-yellow.svg" alt="License Apache 2.0"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://flask.palletsprojects.com/"><img src="https://img.shields.io/badge/Flask-%E2%89%A52.3-339933.svg" alt="Flask"></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-16-336791.svg" alt="PostgreSQL"></a>
  <a href="https://redis.io/"><img src="https://img.shields.io/badge/Redis-Session-DC382D.svg" alt="Redis"></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-%E2%89%A51.0-purple.svg" alt="LangGraph"></a>
</p>

<p align="center"><em>多智能体路由 · 注册登录与会话隔离 · Flask + Postgres + Redis · LangGraph 编排</em></p>

## 项目概述

基于 **LangGraph** 的多智能体智能客服系统，覆盖产品咨询、技术支持、账单、投诉、综合咨询等场景。系统通过意图分类与条件边将请求路由到对应专家 Agent；Web 侧提供 **注册 / 登录**，登录态存 **Redis**，用户与会话目录存 **PostgreSQL**，实现 **按账号隔离的历史对话恢复**。

## 运行效果

### 登录 / 注册

打开 `http://localhost:5000/login`，支持登录与注册切换；登录成功后进入聊天页。

### 首页

![首页](./doc/chat-index.jpg)

### 多轮对话

![多轮对话](./doc/chat-his.jpg)

### 工作流

![工作流](./doc/chat-graph.jpg)

## 账号体系与会话隔离

### 设计目标

| 能力 | 说明 |
| --- | --- |
| 注册 / 登录 | 用户名 + 密码；密码使用 Werkzeug 哈希存入 Postgres |
| 登录态 | Flask-Session，后端为 **Redis**（`REDIS_URL`） |
| 会话目录 | Postgres 表 `conversations`：`user_id ↔ LangGraph thread_id` |
| 消息镜像 | Postgres 表 `conversation_messages`：登录后可恢复历史正文 |
| 隔离规则 | 用户只能列出 / 打开 / 删除自己的会话；跨用户访问返回 403/404 |
| Checkpointer | 开发：`langgraph dev` 内存 runtime + 业务库镜像；生产：`DATABASE_URI` Postgres Checkpointer |

### 数据流（简图）

```
浏览器
  → 登录/注册（Redis Session）
  → Flask web_app（鉴权 + 按 user_id 过滤）
  → LangGraph API（thread / run / state）
  → 同步会话目录与消息到 Postgres
```

### 核心表结构（业务库）

- `users`：账号与密码哈希
- `conversations`：用户会话目录（绑定 `thread_id`）
- `conversation_messages`：对话轮次镜像（侧栏恢复用）

相关代码：`db.py`、`auth_service.py`、`conversation_store.py`、`web_app.py`。

## 项目结构

```
customer-service-ai-agent/
├── multi_agents/                 # 专家智能体
│   ├── base_agent.py
│   ├── product_agent.py
│   ├── tech_agent.py
│   ├── billing_agent.py
│   ├── complaint_agent.py
│   └── general_agent.py
├── tools/
│   └── query_tools.py            # 意图分类（含 out_of_scope 护栏）
├── templates/
│   ├── login.html                # 登录 / 注册页
│   └── index.html                # 聊天主页面（需登录）
├── scripts/
│   ├── init_db.py                # 初始化 Postgres 业务表
│   ├── start_postgres.ps1        # 本机 conda Postgres 启动（可选）
│   └── start_web.ps1             # 启动 Flask Web（可选）
├── db.py                         # Postgres 连接与建表
├── auth_service.py               # 注册 / 登录 / 用户查询
├── conversation_store.py         # 会话目录与消息镜像
├── web_app.py                    # Flask 网关（Redis Session + 鉴权 API）
├── chat_web_service.py           # LangGraph REST 调用封装
├── multi_agent_customer_service.py  # LangGraph 图（分类 → 路由 → 汇聚）
├── session_manager.py            # LangChain 会话管理（可选后端）
├── config.py
├── langgraph.json
├── docker-compose.yml            # 本地 Postgres
├── docker-compose.langgraph.yml  # 生产向 Postgres + Redis / Checkpointer 示例
├── requirements.txt
├── env_example.txt
├── README.md
└── README_LangGraph_CLI.md
```

## 主要特性

1. **模块化专家 Agent**：产品 / 技术 / 账单 / 投诉 / 综合，统一继承 `BaseAgent`
2. **意图分类 + 条件路由**：`classify_query` → Conditional Edges → 专家 → `final_response`
3. **Out-of-Scope 护栏**：非业务 / 越狱类请求直接拒答，不进入业务 Agent
4. **注册登录与会话隔离**：Redis Session + Postgres 用户/会话；换账号互不可见
5. **多轮上下文**：图状态 `persisted_dialogue` + 业务库消息镜像
6. **SSE 流式接口**：`/api/chat/stream`

## 环境要求

- Python 3.10+（推荐 3.11，与 `langgraph.json` 一致）
- PostgreSQL 16（Docker 或本机 / conda）
- Redis（本机 `6379` 或容器）
- OpenAI 兼容 LLM API（如 DeepSeek、硅基流动等）

## 安装与配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
pip install langgraph-cli
pip install -U "langgraph-cli[inmem]"
```

Windows 可将 `langgraph.exe` 加入 PATH，或使用绝对路径调用。

### 2. 配置环境变量

复制 `env_example.txt` 为 `.env` 并填写：

```bash
# LLM
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat

# Flask
FLASK_SECRET_KEY=change-me-to-a-long-random-string
FLASK_PORT=5000

# Postgres（用户 + 会话目录 + 消息镜像）
DATABASE_URL=postgresql://cs_user:cs_pass@127.0.0.1:5432/customer_service
DATABASE_URI=postgresql://cs_user:cs_pass@127.0.0.1:5432/customer_service

# Redis（Flask 登录 Session 用 /0；LangGraph 生产队列建议 /1）
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_URI=redis://127.0.0.1:6379/1

LANGGRAPH_API_URL=http://127.0.0.1:2024
LANGGRAPH_GRAPH_NAME=customer_service
```

### 3. 启动 Postgres + Redis 并建表

**方式 A：Docker Postgres**

```bash
docker compose up -d postgres
python scripts/init_db.py
```

**方式 B：本机已有 Postgres / conda 环境**

```powershell
# 可选：scripts\start_postgres.ps1
python scripts/init_db.py
```

Redis：本机已监听 `6379` 时可直接使用；也可用 `docker-compose.langgraph.yml` 中的 redis 服务。

### 4. 图结构自检（可选）

```bash
python multi_agent_customer_service.py
```

## 运行说明

### 方式 1：Studio UI（仅 LangGraph）

```bash
# Windows 建议
set PYTHONUTF8=1
langgraph dev --no-browser
```

Studio：`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`  
API Docs：`http://127.0.0.1:2024/docs`

### 方式 2：Web + 登录（推荐）

需要 **两个终端**：

```bash
# 终端 1：LangGraph
set PYTHONUTF8=1
langgraph dev --no-browser

# 终端 2：Flask（也可 scripts/start_web.ps1）
python web_app.py
```

1. 打开 **http://localhost:5000/login**
2. 注册账号并登录
3. 进入聊天页：新建会话、多轮对话、侧栏查看历史
4. 退出后换账号：只能看到各自会话

> 说明：`langgraph dev` 默认内存 runtime；对话会同步镜像到 Postgres，因此重启 LangGraph 后，登录仍可从业务库恢复历史。生产环境请使用带 `DATABASE_URI` + `REDIS_URI` 的持久化 Agent Server（参考 `docker-compose.langgraph.yml` 与官方 standalone 文档）。

### 方式 3：直接调用 LangGraph REST

需先 `langgraph dev`。接口参考官方 API 文档。

## 主要 HTTP 接口（Flask）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/login` | 登录 / 注册页 |
| GET | `/` | 聊天页（需登录） |
| POST | `/api/auth/register` | 注册并建立 Session |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/chat` | 同步聊天（需登录，按用户绑定 thread） |
| POST | `/api/chat/stream` | SSE 流式聊天 |
| GET | `/api/sessions` | **仅当前用户**的会话列表 |
| GET/DELETE | `/api/sessions/<id>` | 会话详情 / 删除（校验归属） |
| POST | `/api/new_session` | 创建新 LangGraph thread 并写入目录 |
| GET | `/api/health` | 健康检查（含 Postgres / Redis） |

## 智能体工作流程

```
客户查询 → 鉴权 / 会话归属 → 查询分类 → 智能体路由 → 专业处理 → 最终响应
                ↓                                              ↓
         Postgres 会话目录                              镜像消息 + Checkpointer
```

条件路由标签：`product_info` / `technical_support` / `billing` / `complaint` / `general_inquiry` / `out_of_scope`。

图状态 `AgentState` 关键字段：`customer_query`、`query_type`、`current_agent`、`response`、`session_id`、`persisted_dialogue` 等。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 编排 | LangGraph、LangGraph CLI |
| Agent / LLM | LangChain Core、OpenAI 兼容 API |
| Web | Flask、Jinja2、SSE |
| 登录态 | Redis + Flask-Session |
| 业务持久化 | PostgreSQL（用户 / 会话 / 消息） |
| 生产 Checkpointer | PostgreSQL（`DATABASE_URI`） |

## LLM 配置说明

默认通过 OpenAI 兼容接口调用（如 DeepSeek、硅基流动等），在 `.env` 中配置 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` 即可。

## 扩展指南

### 新增专家 Agent

1. 在 `multi_agents/` 新建类，继承 `BaseAgent` 并实现 `process`
2. 在 `multi_agents/__init__.py` 导出
3. 在 `multi_agent_customer_service.py` 的 `make_graph()` 中增加节点与条件边标签
4. 同步扩展 `tools/query_tools.py` 的分类标签

### 新增工具

1. 在 `tools/` 用 `@tool` 定义
2. 在 `tools/__init__.py` 导出

## 常见问题

**Q: 打开首页被跳到登录？**  
A: 正常。聊天页需登录；访问 `/login` 注册即可。

**Q: 换账号还能看到别人的会话吗？**  
A: 不能。会话列表与详情均按 `user_id` 过滤。

**Q: Windows 上 `langgraph dev` 报 GBK / UnicodeDecodeError？**  
A: 启动前设置 `PYTHONUTF8=1`（及可选 `PYTHONIOENCODING=utf-8`）。

**Q: 问退款类问题曾出现 HTTP 500？**  
A: 旧版账单匹配逻辑有 bug，已在 `billing_agent.py` 修复；请使用最新代码。

**Q: `/api/health` 显示 postgres/redis 异常？**  
A: 检查 Postgres / Redis 是否启动，以及 `.env` 中 `DATABASE_URL`、`REDIS_URL` 是否正确。

## 相关文档

- [README_LangGraph_CLI.md](README_LangGraph_CLI.md)
- [langgraph.json](langgraph.json)
- [env_example.txt](env_example.txt)
- [LangGraph CLI 配置](https://docs.langchain.com/langgraph-platform/cli#configuration-file)
