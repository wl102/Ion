# Ion

网络安全渗透测试Agent。支持动态规划攻击路径图谱、任务持久化、Skills 渐进式披露、以及完整的可观测性。

可作为第三方 Python 库导入使用，也提供 CLI 入口。

## 安装

```bash
uv pip install -e .
# 或使用 pip
pip install -e .
```

可选依赖（DuckDuckGo 搜索）：

```bash
uv pip install -e ".[pentest]"
```

## 快速开始

### 三方库模式

```python
from Ion import PentestAgent

agent = PentestAgent()
result = agent.run("scan 127.0.0.1 with nmap")
print(result)

# 查看 Token 用量
print(agent.get_usage_summary())

# 保存任务图谱
agent.save_tasks("attack_plan.json")
```

### CLI 模式

```bash
# 单条查询
ion "scan 192.168.1.1 with nmap"

# 交互模式
ion -i

# 加载预定义任务图谱
ion --task-file attack_plan.json "execute the next ready task"
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `MODEL_ID` | 模型 ID |
| `OPENAI_BASE_URL` | API Base URL |
| `OPENAI_API_KEY` | API Key |

## 架构

### Agent 循环

基于 ReAct 模式的 LLM Agent 循环：
- `PentestAgent.run(query)` 启动对话
- `run_one_turn()` 调用 LLM API，处理 tool_calls
- `run_agent_loop()` 循环执行直到任务完成

### 任务管理

`TaskManager` 支持攻击路径图谱的动态规划：
- 任务状态：`pending` → `running` → `completed`/`failed`/`killed`
- 依赖关系：`depend_on` 声明前置任务
- 就绪队列：`get_ready_tasks()` 返回依赖已满足的任务
- 持久化：`save_to_file()` / `load_from_file()`

### Skills 系统

遵循 [Agent Skills](https://agentskills.dev) 规范，支持渐进式披露：

1. **Catalog（Tier 1）**：启动时扫描 `~/.ion/skills/` 和 `~/.agents/skills/`，将 `name` + `description` 注入系统提示
2. **Instructions（Tier 2）**：LLM 调用 `activate_skills` 工具加载完整 `SKILL.md` body
3. **Resources（Tier 3）**：Skill 中的 `scripts/`、`references/`、`assets/` 按需读取

内置 Skills：
- `nmap` — 网络扫描
- `nuclei` — 漏洞扫描
- `sqlmap` — SQL 注入测试
- `dirsearch` — 目录爆破
- `ffuf` — Web Fuzzing

自定义 Skill：在 `~/.ion/skills/<skill-name>/SKILL.md` 中按规范编写即可自动加载。

### 可观测性

`ObservabilityLogger` 自动记录：
- Token 用量：`prompt_tokens`, `completion_tokens`, `total_tokens`
- 工具调用：`timestamp`, `tool_name`, `arguments`, `output`, `duration_ms`
- 完整对话：JSON Lines 格式

默认存储在 `~/.ion/logs/` 目录，按日期分文件。

## 工具清单

| 工具 | 说明 |
|------|------|
| `bash_exec` | 执行 shell 命令（带安全黑名单） |
| `python_exec` | 执行 Python 代码 |
| `http_request` | HTTP GET/POST 请求 |
| `web_search` | DuckDuckGo 搜索 |
| `create_task` | 创建任务节点 |
| `update_task` | 更新任务状态/结果 |
| `delete_task` | 删除任务节点 |
| `list_tasks` | 列出所有任务 |
| `get_attack_graph` | 获取攻击图谱（DAG） |
| `activate_skills` | 激活 Skill 加载完整指令 |
| `list_skills` | 列出可用 Skills |
| `run_subagent` | 运行子 Agent 处理子任务 |

## 评估集

[Xbow-benchmark](https://github.com/xbow-engineering/validation-benchmarks)
