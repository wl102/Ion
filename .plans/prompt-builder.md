## Prompt Builder Architecture

系统提示词采用 **Section-based** 分层组装，废弃旧的 Static / Dynamic 命名。

### Section 架构

| Section | 内容 | 可配置 |
|---------|------|--------|
| 1. Core Identity | Persona, Primary Directive, Core Responsibilities | 否 |
| 2. Operational Mode | 当前运行模式提示 (ctf / pentest / aggressive / stealthy) | 是 |
| 3. Operational Doctrine | Domain Knowledge, Execution Principles, Attack Path Graph Planning, Tool Guidelines | 是 |
| 4. Delegation & Sub-Agents | 子 Agent 委托规则 + AGENT.MD 目录 | 条件 |
| 5. Mission Context | 用户目标、任务图状态、可用工具、执行历史等运行时上下文 | 否 |
| 6. Output Standards | 输出格式要求 | 否 |

### 关键设计决策

- **Tool Guidelines 顶层设计**：不再对每个工具（bash / python_exec / http_request）做单独介绍，只保留通用原则、委托策略、攻击图执行工作流、重规划指南。
- **Attack Path Graph Planning**：新增独立的提示词模块，指导 Agent 构建 DAG 结构的攻击路径图，包含依赖设计、状态感知规划、动态扩展、收敛规则。
- **向后兼容**：`PromptBuilder.__init__` 仍接受 `dynamic_config` 参数，但内部已统一为 `prompt_config`。
