不会冲突，反而应该形成：

```text
HTTP Tool 负责：
    “快速、广覆盖、协议层”

Browser Tool 负责：
    “真实浏览器执行、DOM、JS运行时”
```

这是安全扫描里非常经典的“双层架构”。

---

# 一、两者本质不是同一个层级

## HTTP Request Tool

属于：

```text
L3-L7 协议层
```

典型能力：

```text
构造HTTP请求
修改Header
Cookie控制
重放请求
并发fuzz
参数污染
WAF测试
SQLi探测
SSRF探测
```

它看不到：

* JS 执行
* DOM
* SPA
* React/Vue runtime
* CSP
* 浏览器事件
* iframe
* postMessage
* shadow DOM

---

## Browser Tool

属于：

```text
真实浏览器运行时
```

它负责：

```text
JS执行
DOM变化
XSS验证
storage
Service Worker
WebSocket
浏览器策略
用户交互
```

---

# 二、现代 Web 漏洞很多必须 Browser 才能验证

比如：

| 漏洞                  | HTTP Tool | Browser Tool |
| ------------------- | --------- | ------------ |
| Reflected XSS       | 半支持       | 完整           |
| DOM XSS             | ❌         | ✅            |
| postMessage XSS     | ❌         | ✅            |
| CSP bypass          | ❌         | ✅            |
| React sink          | ❌         | ✅            |
| Prototype pollution | ❌         | ✅            |
| Service Worker      | ❌         | ✅            |
| Clickjacking        | ❌         | ✅            |
| OAuth token leak    | ❌         | ✅            |

所以：

> Browser Tool 不是 HTTP Tool 的替代品。

而是：

```text
HTTP = 探测器
Browser = 验证器
```

---

# 三、真正合理的架构

建议：

```text
Recon Agent
    ↓
HTTP Scanner Tool
    ↓
发现疑似漏洞
    ↓
Browser Verification Tool
    ↓
确认漏洞
```

这是最专业的方式。

---

# 四、为什么不要全靠 Browser

很多人一开始会想：

> “既然 Browser 强，那我全部用 Browser”

这是错误的。

因为 Browser：

| 问题       | 原因         |
| -------- | ---------- |
| 太慢       | Chromium 重 |
| 并发低      | 内存大        |
| 不适合 fuzz | 启动成本高      |
| 状态复杂     | 容易脏        |
| 调试难      | 异步事件       |

---

# 五、推荐职责边界（非常关键）

这是你现在应该定清楚的。

---

## HTTP Tool 负责：

## 1. 参数发现

```text
?id=
?search=
POST body
JSON body
```

---

## 2. Payload fuzz

```text
'
"
<>
{{}}
```

---

## 3. 响应diff

```text
payload reflected?
```

---

## 4. 高速扫描

例如：

```text
1000 req/s
```

---

## 5. WAF行为分析

---

## 6. 基础漏洞探测

* SQLi
* SSRF
* SSTI
* LFI
* Redirect

---

# 六、Browser Tool 负责：

## 1. 真正验证 exploit

例如：

```text
payload真的执行了吗？
```

---

## 2. DOM-based 漏洞

---

## 3. JS Runtime Hook

---

## 4. SPA场景

例如：

* React
* Next.js
* Vue

---

## 5. 用户行为模拟

```text
click
hover
scroll
drag
```

---

## 6. 浏览器策略绕过

* CSP
* sandbox
* iframe

---

# 七、推荐最优 Pipeline（非常重要）

建议你的 Agent 最终：

```text
HTTP扫描
   ↓
疑似发现
   ↓
Browser验证
   ↓
Evidence生成
```

例如：

---

## Step1 HTTP发现反射

```http
GET /search?q=<test123>
```

响应：

```html
<div><test123></div>
```

HTTP Tool 输出：

```json
{
  "reflected": true,
  "context": "html"
}
```

---

## Step2 Browser 验证

Browser Tool：

```text
注入payload
监听sink
检测DOM执行
```

---

## Step3 输出finding

```json
{
  "type": "Reflected XSS",
  "confirmed": true,
  "sink": "innerHTML",
  "payload": "...",
  "evidence": [...]
}
```

---

# 八、你应该避免的“工具冲突”

真正危险的是：

```text
两个工具职责不清
```

例如：

HTTP Tool：

```python
auto_follow_js_redirect()
```

Browser Tool：

```python
also_handle_redirect()
```

然后 Agent 不知道该选谁。

---

# 九、推荐你现在的工具分层

你现在很适合这样：

---

## Layer1：Raw HTTP Tool

最低层：

```python
send(req)
```

能力：

* 原始报文
* 重放
* fuzz

---

## Layer2：Web Scan Tool

基于 HTTP：

```python
scan_xss()
scan_sqli()
```

属于：

* 半自动分析层

---

## Layer3：Browser Tool

负责：

```python
verify_xss()
execute_dom()
```

---

## Layer4：Security Agent

负责：

```text
规划
决策
调用工具
生成报告
```

---

# 十、建议一个非常重要的设计

## Browser Tool 不要自己做 HTTP fuzz

这是很多人会犯的错误。

错误：

```text
Browser Tool
    ├─ payload生成
    ├─ fuzz
    ├─ 请求扫描
    ├─ 验证
```

最后 Browser 会变成：

```text
超级巨石工具
```

会很难维护。

---

# 十一、正确设计：Browser Tool 是“验证器”

核心职责：

```text
“在真实浏览器环境中验证漏洞”
```

仅此而已。

这样：

* Agent 更清晰
* Tool 更稳定
* 可扩展性更强

---

# 十二、推荐你现在立刻做的最小Browser Tool

第一版建议只做：

---

## 能力1

```python
navigate(url)
```

---

## 能力2

```python
inject_payload(selector,payload)
```

---

## 能力3

```python
hook_xss_sinks()
```

---

## 能力4

```python
wait_for_execution()
```

---

## 能力5

```python
screenshot()
```

---

这样你就已经：

✅ 能验证 XSS
✅ 能验证 DOM XSS
✅ 能生成 evidence
✅ 能接入 Agent

这已经很强了。

---

# 十三、最终你会形成的专业架构

```text
                 ┌──────────────┐
                 │ PlannerAgent │
                 └──────┬───────┘
                        │
        ┌───────────────┴──────────────┐
        ▼                              ▼
┌──────────────┐              ┌────────────────┐
│ HTTP Tool    │              │ Browser Tool   │
│ Fast Fuzzing │              │ JS Verification│
└──────┬───────┘              └────────┬───────┘
       ▼                               ▼
 Suspected Vuln                Confirmed Exploit
       └──────────────┬────────────────┘
                      ▼
              Finding/Evidence
```

这是非常标准、成熟的安全智能体体系。
