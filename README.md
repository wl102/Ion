# Ion · Autonomous Cybersecurity Penetration Agent

> 🌐 **Languages**: **English (current)** · [简体中文](./README_CN.md)

<p align="center">
  <b>Hand penetration testing over to a self-evolving AI agent.</b><br/>
  Dynamic attack DAG · Sub-agent orchestration · Progressive Skills disclosure · End-to-end observability
</p>

<p align="center">
  <a href="#-quick-start">🚀 Quick Start</a> ·
  <a href="#-architecture">🏗 Architecture</a> ·
  <a href="#-built-in-capabilities">🧰 Capabilities</a> ·
  <a href="#-roadmap">🗺 Roadmap</a>
</p>

---

## 🎯 What is it?

**Ion** is an autonomous-agent framework purpose-built for **cybersecurity penetration testing**. It is more than a ReAct loop wrapped around an LLM — it models the **pentester's actual workflow** as a first-class citizen: **objective decomposition → attack graph → task orchestration → sub-agent execution → evidence convergence → experience distillation**.

How Ion differs from generic agent projects:

| Dimension | Generic Agent | **Ion** |
|---|---|---|
| Task model | Sequential calls | **DAG attack graph** with dependencies, ready queue, info-score priority |
| Prompts | Single hardcoded prompt | **Three-layer progressive disclosure** (identity / mode / runtime) |
| Expertise | One omni-prompt | **11 domain sub-agents** + **8 tool Skills** |
| Mode adaptation | Fixed | One-flag switch between `general` / `security` / `ctf` |
| Experience | Forgotten next run | **Auto-distilled into Skills** for next time |
| Observability | print-style logs | JSONL captures of tokens, tool calls, sub-agent lifecycle |
| Surfaces | CLI only | **Library + CLI + Web UI + REST API** |

---

## ✨ Core Features

- 🧠 **Strategic / Tactical two-layer architecture** — The main agent only orchestrates and decides; sub-agents execute specialized tasks concurrently without polluting each other's context.
- 🕸 **Dynamic attack graph (DAG)** — `create_task` / `update_task` let the LLM continuously re-plan during execution. Dependency-driven, not a linear script.
- 🎚 **Three operational modes**
  - `general` — General task orchestration
  - `security` — Penetration assessment (with safety guardrails by default)
  - `ctf` — Capture-the-flag (aggressive, flag-driven decision tree)
- 📚 **Progressive Skills disclosure** ([agentskills.dev](https://agentskills.dev) compliant)
  - **Tier 1 Catalog** — `name + description` injected at startup
  - **Tier 2 Instructions** — Full `SKILL.md` loaded on demand via `activate_skills`
  - **Tier 3 Resources** — `scripts/` `references/` `assets/` lazy-loaded
- 🤖 **Expert sub-agent catalog** — `ReconAgent`, `SQLInjectionAgent`, `XSSAgent`, `SSRFDetectionAgent`, …
- 🔁 **Self-evolution** — Calls `skill_manage` after non-trivial tasks to distill the experience.
- 📈 **Production-grade observability** — JSONL files in `~/.ion/logs/` rotated by date: tokens, tools, sub-agent spawn/finish/redelegation.
- 💾 **Persistence** — SQLite / MySQL / PostgreSQL via SQLAlchemy: sessions, tasks, messages, hooks.
- 🌐 **Web console** — FastAPI + static frontend; start/stop sessions, inspect graphs, stream logs from the browser.
- 🪝 **Runtime hooks** — Inject user messages into a running agent without breaking the main loop.

---

## 📊 Benchmark Results

Based on [XBOW validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks) (104 real-world Web security targets covering IDOR / SQLi / XSS / SSRF / RCE):

### 🏆 Overall

| Metric | Value |
|---|---|
| **Overall pass rate** | **96 / 104 = 92.3%** |
| Average token consumption | ~1,685K / benchmark |
| Average completion time | ~9.6 min / benchmark |

### 📈 By Difficulty Level

| Level | Pass / Total | Rate | Avg Tokens | Avg Duration |
|:---:|:---:|:---:|---:|---:|
| **L1** | 45 / 45 | **100.0%** | ~1,516K | ~5.9 min |
| **L2** | 46 / 51 | **90.2%** | ~1,705K | ~12.4 min |
| **L3** | 5 / 8 | **62.5%** | ~3,018K | ~18.2 min |

> 📌 Data source: `benchmark_results_*.json` / `success_benchmarks.json` in repo root. Run `python total.py` to reproduce. Model: OpenAI-compatible model configured via `MODEL_ID`.

---

## 🚀 Quick Start

### Install

```bash
git clone <your-fork-url> Ion && cd Ion

uv pip install -e .
# or
pip install -e .

# Optional: DuckDuckGo search
uv pip install -e ".[pentest]"
```

### Configure

Copy `.env.example` to `.env` and fill in:

```bash
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_API_KEY  = "sk-xxxxxxxx"
MODEL_ID        = "gpt-4o"          # any OpenAI-compatible model

AGENT_MAX_LOOP      = 100           # main loop cap, 0 = unlimited
SUB_AGENT_MAX_LOOP  = 50            # sub-agent budget
CONTEXT_MAX_TOKENS  = 128000        # context-compression threshold

ION_LOG_DIR         = "./logs"
# ION_DATABASE_URL  = "sqlite:////absolute/path/to/ion.db"
```

### Docker (Recommended)

The fastest way to run Ion is with Docker Compose:

```bash
# Pre-create the SQLite file so Docker bind-mounts it as a file, not a directory
touch ion.db

# Build and start the web console
docker compose up --build
```

Then open `http://localhost:8000`.  
The compose file mounts `./data`, `./logs`, and `./ion.db` for persistence. To run CLI or library mode inside the container:

```bash
docker compose run --rm ion ion "scan 192.168.1.1 with nmap"
```

### Three ways to use Ion

#### 1️⃣ As a Python library

```python
from Ion import IonAgent

agent = IonAgent(mode="ctf")            # general / security / ctf
result = agent.run("Penetrate target 10.0.0.5:80 and capture the flag")

print(result)
print(agent.get_usage_summary())        # token usage
agent.save_tasks("attack_plan.json")    # persist the task graph
```

#### 2️⃣ CLI

```bash
# Single query
ion "scan 192.168.1.1 with nmap"

# Interactive mode
ion -i

# CTF mode + load a predefined graph
ion --agent-mode ctf --task-file plan.json "execute the next ready task"

# Cap turn count
ion --max-turns 50 "asset inventory"
```

#### 3️⃣ Web console

```bash
uvicorn Ion.web.app:app --host 0.0.0.0 --port 8080
# Open http://localhost:8080
```

Includes session management, live task-graph view, streaming logs, persisted messages.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User / CLI / Web Frontend                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                  ┌──────────▼───────────┐
                  │     IonAgent         │  ← Strategic Orchestrator
                  │  (Strategic Layer)   │
                  └──────────┬───────────┘
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
 ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
 │ TaskManager │     │ SkillRegistry│     │AgentRegistry │
 │  (DAG)      │     │ (progressive)│     │ (sub-agents) │
 └─────────────┘     └──────────────┘     └──────────────┘
        │                    │                    │
        └─────────┬──────────┴───────────┬────────┘
                  ▼                      ▼
        ┌──────────────────┐   ┌────────────────────┐
        │  Tools Registry  │   │ run_subagent_loop  │ ← Tactical Layer
        │ (bash/http/...)  │   │ (Tactical Workers) │
        └────────┬─────────┘   └──────────┬─────────┘
                 │                        │
                 └──────────┬─────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ ObservabilityLogger  │ → JSONL logs
                 │ + DB (SQLAlchemy)    │ → persistence
                 └──────────────────────┘
```

### Module map

| Path | Responsibility |
|---|---|
| `src/Ion/agent.py` | `IonAgent` entry class; wires prompt / tools / registries |
| `src/Ion/ion.py` | Main loop: `run_agent_loop` / `run_one_turn` / `run_subagent_loop` |
| `src/Ion/prompts/builder.py` | Three-layer prompt assembly (identity / mode / runtime) |
| `src/Ion/tools/` | `bash_exec` `python_exec` `http_request` `web_search` `task_tool` `spawn_tool` `skill_tool` |
| `src/Ion/skills/` | Built-in Skills: nmap / nuclei / sqlmap / dirsearch / ffuf + ctf-common-patterns + privilege-escalation + web-rce-chain |
| `src/Ion/agents/` | 11 domain sub-agents: Recon / SQLi / XSS / SSRF / FileUpload / DirBrute / AuthBypass / WebFingerprint / VulnScan / PrivEsc / PostExploit |
| `src/Ion/db/` | SQLAlchemy models: `SessionRecord` / `TaskRecord` / `MessageRecord` / `HookRecord` |
| `src/Ion/web/` | FastAPI app + static frontend |
| `src/Ion/observability.py` | JSONL logger covering tokens / tools / sub-agents / context compression |

### Three prompt layers

| Layer | Content | When it changes |
|---|---|---|
| Layer 1 — Identity | Persona, Primary Directive, Core Responsibilities, Self-Improvement | Fixed at startup |
| Layer 2 — Mode | `general` / `security` / `ctf` template | Picked at startup based on `mode` |
| Layer 3 — Runtime | User goal, current task graph, Skills catalog, tool schema, conversation summary | **Refreshed every turn** |

The `_on_before_turn` callback inside `agent.run()` rebuilds the system message before every LLM call so the graph / history / Skill activation state is always in sync with reality.

---

## 🧰 Built-in Capabilities

### Tools

| Tool | What it does |
|---|---|
| `bash_exec` | Run shell commands (blacklist + timeout) |
| `python_exec` | Run Python code (sandboxed `exec`) |
| `http_request` | HTTP GET / POST / PUT / DELETE |
| `web_search` | DuckDuckGo search |
| `create_task` / `update_task` / `delete_task` / `list_tasks` | Task graph CRUD |
| `add_task_note` | Annotate task execution (used for reflection) |
| `get_attack_graph` | Fetch the DAG |
| `list_skills` / `activate_skills` | Skill catalog and loading |
| `skill_manage` | **Create / update / delete custom Skills** (the self-evolution entry) |
| `list_subagents` / `spawn_subagent` | Sub-agent dispatch |

### Skills (out of the box)

| Skill | Category | Purpose |
|---|---|---|
| `nmap` | recon | Port scan, service detection, OS fingerprinting |
| `nuclei` | vuln-scan | Templated vulnerability scanning |
| `sqlmap` | exploit | Automated SQL injection |
| `dirsearch` | recon | Directory brute-forcing |
| `ffuf` | recon | Web fuzzing |
| `ctf-common-patterns` | ctf | CTF payloads / flag locations cheat-sheet |
| `privilege-escalation` | post-exploit | Linux/Windows privesc checklist |
| `web-rce-chain` | exploit | Web vulnerability chain → RCE patterns |

> 💡 Custom Skills: drop a `~/.ion/skills/<name>/SKILL.md` following the spec and it auto-loads. Resources go under `scripts/` `references/` `assets/` in the same directory.

### Sub-agents

| Sub-agent | Specialty |
|---|---|
| `ReconAgent` | Asset discovery, ports, services, OSINT |
| `WebFingerprintAgent` | Web app fingerprinting & tech stack ID |
| `VulnerabilityScanAgent` | General vulnerability scanning & orchestration |
| `SQLInjectionAgent` | SQL injection detection & exploitation |
| `XSSAgent` | XSS discovery & payload crafting |
| `SSRFDetectionAgent` | SSRF & internal-network probing |
| `FileUploadAgent` | File upload bypasses |
| `DirBruteAgent` | Directory & hidden-resource brute-forcing |
| `AuthBypassAgent` | Auth bypass & weak-credential testing |
| `PrivilegeEscalationAgent` | Local privilege escalation |
| `PostExploitAgent` | Post-exploitation, lateral movement, cleanup |

> 💡 Custom sub-agents: `~/.ion/agents/<name>/AGENT.md`, frontmatter must contain `name` and `description`.

---

## 📊 Observability

Files auto-generated under `~/.ion/logs/` (rotated by date):

```
logs/
├── tools_2026-05-05.jsonl         # every tool call: tool_name / arguments / output / duration_ms
├── conversation_2026-05-05.jsonl  # full conversation snapshots
├── subagents_2026-05-05.jsonl     # sub-agent spawn / finish / redelegation
└── usage_2026-05-05.json          # cumulative tokens
```

Every record carries `run_id` / `parent_run_id` / `agent_name`, so you can reconstruct the full parent/child call tree in jq / DuckDB / your favorite log UI.

---

## 🗺 Roadmap

### ✅ Done

- [x] Three-layer Prompt Builder (identity / mode / runtime)
- [x] DAG task graph + dependency-driven ready queue + info-score priority
- [x] Progressive Skills disclosure (Tier 1/2/3) + auto-sync into `~/.ion/skills/`
- [x] 11 built-in domain sub-agents
- [x] `spawn_subagent` controlled delegation (budget, similarity guard, structured return)
- [x] Tools: bash / python / http / web_search / task / skill / spawn / agent_graph
- [x] ObservabilityLogger: tokens + tools + sub-agents + context compression
- [x] Persistence: SQLAlchemy multi-backend (SQLite / MySQL / PostgreSQL)
- [x] FastAPI Web API + static-frontend console
- [x] CLI (query / interactive / task-file / mode switching)
- [x] CTF mode: vulnerability-confirmation protocol + decision tree + tiered IDOR
- [x] Self-evolution: `skill_manage` distills experience
- [x] Sub-agent execution streamed live to chat
- [x] LLM auto-generated session titles + chat-first welcome UI
- [x] Context compression (auto-summarize history past threshold)

### 🚧 In progress

- [ ] **MCP integration** — let Ion act as both an MCP server and an MCP-tool consumer
- [ ] **Multi-modal evidence chain** — screenshots, packet captures, binary artifacts in the graph
- [x] **Benchmarks** — wired up [Xbow validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks); 96/104 (92.3%) regression baseline established
- [ ] **Skill marketplace** — one-click install / share community SKILL.md

### 🔮 Backlog (contributions welcome)

- [ ] **Replay & time-travel** — Session replay and branch-debug from JSONL logs
- [ ] **Multi-agent collaboration protocol** — Cross-agent finding sharing, redundant-scan avoidance
- [ ] **Guardrails** — Target whitelist, command double-confirm, brute-force rate limits
- [ ] **More modes** — `bug-bounty` / `red-team` / `purple-team`
- [ ] **Report generator** — Auto-produce Markdown / PDF pentest reports
- [ ] **Browser-use integration** — Real-browser interaction for complex web apps
- [ ] **Traffic proxy (mitm)** — Automated Burp alternative with passive capture + active replay

---

## ⚖️ Safety Notice

Ion is intended for **authorized** penetration testing, red/blue-team exercises, and CTF training.  
Scanning, exploiting, or exfiltrating against any target without explicit authorization **is illegal**. The user is fully responsible for any legal consequences.

---

## 📐 Evaluation Benchmark

See [Benchmark Results](#-benchmark-results) above for detailed scores.

---

## 🤝 Contributing

Issues and PRs are welcome, especially for:

- New Skills (please follow the [agentskills.dev](https://agentskills.dev) spec)
- New domain sub-agents (AGENT.md frontmatter must contain `name` and `description`)
- Bug fixes and documentation improvements

---

## 📄 License

See LICENSE for details.
