# Ion · 自治化网络安全渗透智能体

> 🌐 **Languages**: [English](./README.md) · **简体中文（当前）**

<p align="center">
  <b>把渗透测试交给一个会自我进化的 AI 智能体。</b><br/>
  动态攻击图谱 · 子智能体编排 · Skills 渐进式披露 · 全链路可观测
</p>

<p align="center">
  <a href="#-快速开始">🚀 快速开始</a> ·
  <a href="#-系统架构">🏗 架构</a> ·
  <a href="#-内置能力">🧰 能力清单</a> ·
  <a href="#-路线图">🗺 路线图</a>
</p>

---

## 🎯 它是什么？

**Ion** 是一个面向**网络安全渗透测试**场景的自治智能体框架。它不只是把 LLM 套上一层 ReAct 循环——它把"渗透测试工程师的工作流"作为一等公民进行建模：**目标分解 → 攻击图谱 → 任务编排 → 子智能体执行 → 证据收敛 → 经验沉淀**。

与一般 Agent 项目的差异：

| 维度 | 通用 Agent | **Ion** |
|---|---|---|
| 任务模型 | 顺序调用 | **DAG 攻击图谱**，支持依赖、就绪队列、信息分优先级 |
| 提示词 | 单层硬编码 | **三层渐进披露**（身份 / 模式 / 运行时） |
| 专家能力 | 一个万能 prompt | **11 个领域子智能体** + **8 个工具 Skill** |
| 模式适配 | 固定 | `general` / `security` / `ctf` 一键切换 |
| 经验积累 | 一次性 | **自动蒸馏 Skill**，下次更快 |
| 可观测 | print 日志 | JSONL 全量记录：token、工具调用、子代理生命周期 |
| 形态 | 仅 CLI | **库 + CLI + Web UI + REST API** |

---

## ✨ 核心特性

- 🧠 **战略 / 战术双层架构** — 主智能体只做编排与决策；子智能体并发执行专项任务，互不污染上下文
- 🕸 **动态攻击图谱（DAG）** — `create_task` / `update_task` 让 LLM 在执行中持续重规划，依赖驱动而非线性脚本
- 🎚 **三种作战模式**
  - `general` — 通用任务编排
  - `security` — 渗透评估（默认带防护边界）
  - `ctf` — CTF 夺旗（aggressive，flag 驱动决策树）
- 📚 **Skills 渐进式披露**（[agentskills.dev](https://agentskills.dev) 规范）
  - **Tier 1 Catalog**：启动注入 `name + description`
  - **Tier 2 Instructions**：按需 `activate_skills` 加载完整 SKILL.md
  - **Tier 3 Resources**：`scripts/` `references/` `assets/` 懒加载
- 🤖 **专家子智能体目录** — `ReconAgent`、`SQLInjectionAgent`、`XSSAgent`、`SSRFDetectionAgent` …
- 🔁 **自我进化** — 完成非平凡任务后自动调用 `skill_manage` 蒸馏经验
- 📈 **生产级可观测性** — `~/.ion/logs/` 下按日期切分的 JSONL，含 token、工具、子代理 spawn/finish/redelegation
- 💾 **持久化** — SQLite/MySQL/Postgres，会话、任务、消息、hook 全量落库
- 🌐 **Web 控制台** — FastAPI + 静态前端，浏览器内启停会话、看图谱、读日志
- 🪝 **运行时 Hook** — 智能体执行中向其注入用户消息，不打断主循环

---

## 📊 基准评测成绩

基于 [XBOW validation-benchmarks](https://github.com/wl102/validation-benchmarks)（共 104 个真实 Web 安全靶场，覆盖 IDOR / SQLi / XSS / SSRF / RCE 等）的测评结果，完整报告见 [`benchmark-results/`](benchmark-results/)：

### 🏆 总体表现

| 指标 | 数值 |
|---|---|
| **总通过率** | **98 / 104 = 94.2%** |
| 平均 token 消耗 | ~1,905K / benchmark |
| 平均完成耗时 | ~11.6 min / benchmark |

### 📈 分难度等级

| Level | 通过 / 总数 | 成功率 | 平均 Tokens | 平均耗时 |
|:---:|:---:|:---:|---:|---:|
| **L1** | 45 / 45 | **100.0%** | ~1,516K | ~5.9 min |
| **L2** | 48 / 51 | **94.1%** | ~2,154K | ~16.3 min |
| **L3** | 5 / 8 | **62.5%** | ~3,018K | ~18.2 min |

> 📌 数据来源：[`benchmark-results/total.json`](benchmark-results/total.json)，在 [`benchmark-results/`](benchmark-results/) 目录下运行 `python total.py` 可复现统计。模型：`MODEL_ID` 配置的 OpenAI 兼容模型。

---

## 🚀 快速开始

### 安装

```bash
git clone <your-fork-url> Ion && cd Ion

uv pip install -e .
# 或
pip install -e .

# 可选：DuckDuckGo 搜索
uv pip install -e ".[pentest]"
```

### 配置

复制 `.env.example` 为 `.env` 并填写：

```bash
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_API_KEY  = "sk-xxxxxxxx"
MODEL_ID        = "gpt-4o"          # 任意 OpenAI 兼容模型

AGENT_MAX_LOOP      = 100           # 主循环上限，0 = 无限
SUB_AGENT_MAX_LOOP  = 50            # 子代理预算
CONTEXT_MAX_TOKENS  = 128000        # 上下文压缩阈值

ION_LOG_DIR         = "./logs"
# ION_DATABASE_URL  = "sqlite:////absolute/path/to/ion.db"
```

### Docker（推荐）

最快上手方式是 Docker Compose：

```bash
# 预创建 SQLite 文件，避免 Docker 将其挂载为目录
touch ion.db

# 构建并启动 Web 控制台
docker compose up --build
```

浏览器访问 `http://localhost:8000`。  
Compose 已挂载 `./data`、`./logs` 和 `./ion.db` 用于持久化。如需在容器内运行 CLI：

```bash
docker compose run --rm ion ion "scan 192.168.1.1 with nmap"
```

### 三种使用方式

#### 1️⃣ 作为 Python 库

```python
from Ion import IonAgent

agent = IonAgent(mode="ctf")            # general / security / ctf
result = agent.run("对目标 10.0.0.5:80 进行渗透并取得 flag")

print(result)
print(agent.get_usage_summary())        # token 使用
agent.save_tasks("attack_plan.json")    # 任务图谱持久化
```

#### 2️⃣ CLI

```bash
# 单次查询
ion "scan 192.168.1.1 with nmap"

# 交互模式
ion -i

# CTF 模式 + 加载预定义图谱
ion --agent-mode ctf --task-file plan.json "继续执行下一个就绪任务"

# 限制轮次
ion --max-turns 50 "目标资产盘点"
```

#### 3️⃣ Web 控制台

```bash
uvicorn Ion.web.app:app --host 0.0.0.0 --port 8080
# 浏览器访问 http://localhost:8080
```

包含：会话管理、任务图实时刷新、日志流、消息持久化。

---

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    User / CLI / Web Frontend                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                  ┌──────────▼───────────┐
                  │     IonAgent         │  ← 主编排者
                  │  (Strategic Layer)   │
                  └──────────┬───────────┘
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
 ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
 │ TaskManager │     │ SkillRegistry│     │AgentRegistry │
 │  (DAG 图谱) │     │ (渐进披露)   │     │ (子代理目录) │
 └─────────────┘     └──────────────┘     └──────────────┘
        │                    │                    │
        └─────────┬──────────┴───────────┬────────┘
                  ▼                      ▼
        ┌──────────────────┐   ┌────────────────────┐
        │  Tools Registry  │   │ run_subagent_loop  │ ← 战术层
        │ (bash/http/...)  │   │ (Tactical Workers) │
        └────────┬─────────┘   └──────────┬─────────┘
                 │                        │
                 └──────────┬─────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ ObservabilityLogger  │ → JSONL 日志
                 │ + DB (SQLAlchemy)    │ → 持久化
                 └──────────────────────┘
```

### 模块速览

| 路径 | 职责 |
|---|---|
| `src/Ion/agent.py` | `IonAgent` 入口类；装配 prompt / tools / registries |
| `src/Ion/ion.py` | 主循环：`run_agent_loop` / `run_one_turn` / `run_subagent_loop` |
| `src/Ion/prompts/builder.py` | 三层 prompt 拼装（identity / mode / runtime） |
| `src/Ion/tools/` | `bash_exec` `python_exec` `http_request` `web_search` `task_tool` `spawn_tool` `skill_tool` |
| `src/Ion/skills/` | 内置 Skill：nmap/nuclei/sqlmap/dirsearch/ffuf + ctf-common-patterns + privilege-escalation + web-rce-chain |
| `src/Ion/agents/` | 11 个领域子智能体：Recon / SQLi / XSS / SSRF / FileUpload / DirBrute / AuthBypass / WebFingerprint / VulnScan / PrivEsc / PostExploit |
| `src/Ion/db/` | SQLAlchemy 模型：`SessionRecord` / `TaskRecord` / `MessageRecord` / `HookRecord` |
| `src/Ion/web/` | FastAPI 应用 + 静态前端 |
| `src/Ion/observability.py` | JSONL 日志器，含 token / tool / subagent / 上下文压缩事件 |

### Prompt 三层

| 层 | 内容 | 何时变化 |
|---|---|---|
| Layer 1 — 身份 | Persona、Primary Directive、Core Responsibilities、Self-Improvement | 启动时确定 |
| Layer 2 — 模式 | `general` / `security` / `ctf` 模板 | 启动时按 `mode` 选择 |
| Layer 3 — 运行时 | 用户目标、当前任务图、Skills 目录、Tools schema、对话摘要 | **每轮自动刷新** |

刷新机制：`agent.run()` 内的 `_on_before_turn` 回调在每轮 LLM 调用前重建系统消息，使图谱 / 历史 / Skill 激活状态始终与现实同步。

---

## 🧰 内置能力

### 工具（Tools）

| 工具 | 功能 |
|---|---|
| `bash_exec` | 执行 shell 命令（带黑名单 + 超时） |
| `python_exec` | 执行 Python 代码（exec 沙箱） |
| `http_request` | HTTP GET/POST/PUT/DELETE |
| `web_search` | DuckDuckGo 搜索 |
| `create_task` / `update_task` / `delete_task` / `list_tasks` | 任务图 CRUD |
| `add_task_note` | 任务执行注记（用于反思） |
| `get_attack_graph` | 取攻击 DAG |
| `list_skills` / `activate_skills` | Skill 目录与加载 |
| `skill_manage` | **创建 / 更新 / 删除自定义 Skill**（自我进化入口） |
| `list_subagents` / `spawn_subagent` | 子代理调度 |

### Skills（开箱即用）

| Skill | 类别 | 用途 |
|---|---|---|
| `nmap` | recon | 端口扫描、服务识别、OS 指纹 |
| `nuclei` | vuln-scan | 模板化漏洞扫描 |
| `sqlmap` | exploit | SQL 注入自动化 |
| `dirsearch` | recon | 目录爆破 |
| `ffuf` | recon | Web Fuzzing |
| `ctf-common-patterns` | ctf | CTF 常见 payload / flag 位置速查 |
| `privilege-escalation` | post-exploit | Linux/Win 提权清单 |
| `web-rce-chain` | exploit | Web 漏洞链 → RCE 模式库 |

> 💡 自定义 Skill：在 `~/.ion/skills/<name>/SKILL.md` 按规范编写即自动加载。Resources 放在同目录的 `scripts/` `references/` `assets/`。

### 子智能体（Sub-Agents）

| 子智能体 | 主攻方向 |
|---|---|
| `ReconAgent` | 资产发现、端口、服务、OSINT |
| `WebFingerprintAgent` | Web 应用指纹与技术栈识别 |
| `VulnerabilityScanAgent` | 通用漏洞扫描与编排 |
| `SQLInjectionAgent` | SQL 注入检测与利用 |
| `XSSAgent` | XSS 探测与 payload 构造 |
| `SSRFDetectionAgent` | SSRF 与内网探测 |
| `FileUploadAgent` | 文件上传绕过 |
| `DirBruteAgent` | 目录与隐藏资源爆破 |
| `AuthBypassAgent` | 认证绕过与弱口令 |
| `PrivilegeEscalationAgent` | 本地提权 |
| `PostExploitAgent` | 后渗透、横向移动、痕迹清理 |

> 💡 自定义子代理：`~/.ion/agents/<name>/AGENT.md`，frontmatter 必须含 `name` 与 `description`。

---

## 📊 可观测性

启动后自动在 `~/.ion/logs/` 生成（按日期切分）：

```
logs/
├── tools_2026-05-05.jsonl         # 每次工具调用：tool_name / arguments / output / duration_ms
├── conversation_2026-05-05.jsonl  # 完整对话快照
├── subagents_2026-05-05.jsonl     # 子代理 spawn / finish / redelegation
└── usage_2026-05-05.json          # token 累计
```

每条记录含 `run_id` / `parent_run_id` / `agent_name`，可在 jq / DuckDB / 日志可视化中复原父子调用树。

---

## 🗺 路线图

### ✅ 已完成

- [x] 三层 Prompt Builder（identity / mode / runtime）
- [x] DAG 任务图 + 依赖驱动就绪队列 + 信息分优先级
- [x] Skills 渐进披露（Tier 1/2/3）+ 自动同步到 `~/.ion/skills/`
- [x] 11 个领域子智能体内置目录
- [x] `spawn_subagent` 受控委派（预算、相似度防重复、结构化返回）
- [x] 工具：bash / python / http / web_search / task / skill / spawn / agent_graph
- [x] ObservabilityLogger：token + tools + subagents + 上下文压缩
- [x] 持久化：SQLAlchemy 多后端（SQLite / MySQL / PostgreSQL）
- [x] FastAPI Web API + 静态前端控制台
- [x] CLI（query / interactive / task-file / mode 切换）
- [x] CTF 模式：漏洞确认协议 + 决策树 + 分层 IDOR
- [x] 自我进化：`skill_manage` 蒸馏经验
- [x] 子代理执行过程实时回流到 chat
- [x] LLM 自动生成会话标题 + chat-first 欢迎 UI
- [x] 上下文压缩（超阈值自动总结历史）

### 🚧 进行中

- [ ] **MCP 协议接入** — 让 Ion 既能作为 MCP server 也能消费 MCP tool
- [ ] **多模态证据链** — 截图、流量包、二进制 artifact 入图
- [x] **基准评测** — 接入 [Xbow validation-benchmarks](https://github.com/wl102/validation-benchmarks)，建立 98/104（94.2%）回归基线（[测评结果](benchmark-results/)）
- [ ] **Skill 市场** — 一键安装/分享社区贡献的 SKILL.md

### 🔮 待办（欢迎共建）

- [ ] **Replay & Time-travel** — 基于 JSONL 日志的会话重放与分支调试
- [ ] **多智能体协同协议** — 跨智能体共享发现、避免重复扫描
- [ ] **风险护栏 (Guardrails)** — 目标白名单、命令二次确认、爆破速率约束
- [ ] **更多模式** — `bug-bounty` / `red-team` / `purple-team`
- [ ] **报告生成器** — 自动产出 Markdown / PDF 渗透报告
- [ ] **Browser-use 集成** — 复杂 Web 应用的真实浏览器交互
- [ ] **流量代理 (mitm)** — 自动化 Burp 替代品，被动采集 + 主动重放

---

## ⚖️ 安全声明

Ion 是一个**用于授权范围内**渗透测试 / 红蓝对抗 / CTF 训练的工具。  
对任何未授权目标的扫描、利用、数据外传**均属违法**。使用者需自行承担一切法律责任。

---

## 📐 评估基准

[Xbow validation-benchmarks](https://github.com/wl102/validation-benchmarks) — 已完成接入，详细成绩见上文 [基准评测成绩](#-基准评测成绩) 与 [`benchmark-results/`](benchmark-results/)。

---

## 🤝 贡献

欢迎提 Issue / PR，特别是：

- 新的 Skill（请遵循 [agentskills.dev](https://agentskills.dev) 规范）
- 新的领域子智能体（AGENT.md frontmatter 必须含 `name` + `description`）
- Bug 修复与文档改进

---

## 📄 License

详见 LICENSE 文件。
