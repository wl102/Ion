# Ion Web API + 持久化计划

## 目标
为 Ion Agent 增加 Web HTTP API 入口和数据库持久化，支持浏览器对话框启动智能体、Hook 中断输入、任务数据库存储。
前端由他人实现，本计划只定义后端接口与实现。

## 技术栈
- FastAPI + Uvicorn
- SQLAlchemy 2.0（SQLite 默认，预留 MySQL/PostgreSQL）
- SSE (Server-Sent Events) 流式输出

## 模块结构
```
src/Ion/web/
  __init__.py
  schemas.py        # Pydantic 请求/响应模型
  agent_runner.py   # WebAgentRunner：后台运行 Agent + SSE 推送
  api/
    sessions.py     # Session CRUD
    tasks.py        # Attack plan / task CRUD
    agent.py        # Agent 启动 / Hook / SSE
    logs.py         # 日志文件读取
  app.py            # FastAPI 应用入口
```

## 数据库模型 (已完成)
见 `src/Ion/db/models.py`:
- `SessionRecord` — id, title, mode, status, log_dir, created_at, updated_at
- `TaskRecord` — 对应 Task，外键 session_id
- `HookRecord` — 用户 hook 输入，外键 session_id

## API 接口定义

### Session 管理
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions` | 创建 session |
| GET  | `/api/sessions` | 列表（分页） |
| GET  | `/api/sessions/{sid}` | 获取 session 详情 |
| DELETE | `/api/sessions/{sid}` | 删除 session 及其关联数据 |

**POST /api/sessions Request**
```json
{
  "title": "Redis 扫描",
  "mode": "security",
  "query": "扫描 192.168.2.15:16379"
}
```

**Response**
```json
{
  "id": "abc123",
  "title": "Redis 扫描",
  "mode": "security",
  "status": "idle",
  "log_dir": "/home/user/.ion/logs/abc123",
  "created_at": "2026-04-30T12:00:00",
  "updated_at": "2026-04-30T12:00:00"
}
```

### Agent 运行与 Hook
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions/{sid}/run` | 启动/继续运行 agent |
| POST | `/api/sessions/{sid}/hook` | 提交用户 hook 输入 |
| GET  | `/api/sessions/{sid}/stream` | SSE 流式输出 |

**POST /api/sessions/{sid}/run Request**
```json
{ "query": "继续分析" }
```

**POST /api/sessions/{sid}/hook Request**
```json
{ "content": "请先扫描端口再尝试漏洞利用" }
```

**SSE Events**
每行 `data: <json>\n\n`
```json
{"type": "system", "payload": "agent started"}
{"type": "assistant", "payload": "正在分析目标...", "reasoning": false}
{"type": "tool_start", "payload": ["http_request"]}
{"type": "tool_result", "payload": "{\"status\": 200...}", "tool_name": "http_request", "duration_ms": 120}
{"type": "task_update", "payload": {"task_id": "task_xxx", "status": "completed"}}
{"type": "hook_received", "payload": "请先扫描端口再尝试漏洞利用"}
{"type": "done", "payload": "分析完成"}
{"type": "error", "payload": "API key missing"}
```

### Attack Plan / Task
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/{sid}/tasks` | 获取该 session 的任务列表 |
| GET | `/api/sessions/{sid}/attack_graph` | attack_graph_view 文本/JSON |

**GET /api/sessions/{sid}/tasks Response**
```json
[
  {
    "id": "task_5117f85f",
    "name": "Redis服务发现与版本识别",
    "description": "探测目标Redis服务",
    "status": "completed",
    "depend_on": [],
    "result": "发现严重漏洞...",
    "information_score": 5,
    "intelligence_source": ""
  }
]
```

### Logs
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/{sid}/logs` | 读取日志文件列表和内容 |

**Response**
```json
{
  "files": ["tools_2026-04-30.jsonl", "conversation_2026-04-30.jsonl"],
  "content": {
    "tools_2026-04-30.jsonl": [{...}]
  }
}
```

## Hook 机制 (已完成)
- `LoopState.hook_queue: queue.Queue`
- `run_agent_loop` 每轮开始前 `_check_and_inject_hooks` 排空队列，将消息作为 user role 插入
- `IonAgent.submit_hook(content)` 写入队列

## 持久化 TaskManager (已完成)
- `PersistentTaskManager(TaskManager)` 在 `src/Ion/tools/task_tool.py`
- 每次 add/update/delete 先内存操作，再同步写入 `TaskRecord`
- `load_from_db()` 从数据库恢复内存状态

## SSE 与 Agent 运行器设计
`WebAgentRunner` 管理单个 session：
- `sse_queue: asyncio.Queue[dict]` — 异步事件队列
- `agent: IonAgent` — 使用 `PersistentTaskManager`
- `_run(query, mode)` — 在线程池中运行同步 `agent.run()`，通过 callbacks 捕获事件推入 `sse_queue`
- `iter_sse()` — 消费队列 yield SSE 格式字符串
- `submit_hook(content)` — 调用 `agent.submit_hook()` 并推入 `hook_received` 事件

## 依赖变更
`pyproject.toml` 新增：
- fastapi
- uvicorn
- sqlalchemy>=2.0
- python-multipart

## 启动方式
```bash
uvicorn Ion.web.app:app --reload --host 0.0.0.0 --port 8000
```

## 状态
- [x] 核心 Hook 机制 (`ion.py`, `agent.py`)
- [x] 数据库层 (`db/core.py`, `db/models.py`)
- [x] 持久化 TaskManager (`tools/task_tool.py`)
- [x] 依赖安装 (`pyproject.toml`)
- [ ] Web 后端 (`web/app.py`, `web/schemas.py`, `web/agent_runner.py`, `web/api/*.py`)
