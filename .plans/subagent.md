实现子agent 注入系统, 类似skill的实现，默认的name，description注入主智能体，调用执行子智能体工具的时候加载AGENT.md的内容插入子智能体提示词中。

agent schema, 默认扫描路径 ~/.ion/agents/agents/subagent1/AGENT.md，当前目录.ion/agents/subagent1/AGENT.md

```yaml
---
name: subagent1
description: 这是资产探测agent
---
下面是领域知识系统提示词注入到subagent中
```

内置实现下面几个sub agent
- ReconAgent
- WebFingerprintAgent
- DirBruteAgent
- VulnerabilityScanAgent
- XSSAgent
- SQLInjectionAgent
- SSRFDetectionAgent
- FileUploadAgent
- AuthBypassAgent
- PostExploitAgent
- PrivilegeEscalationAgent
