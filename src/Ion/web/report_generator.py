"""Penetration test report generator.

Produces rich PDF reports from session data (tasks, messages, attack graph)
by rendering Markdown → HTML → Playwright PDF.
"""

from __future__ import annotations

import html as html_module
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import markdown

from Ion.web.pdf_service import get_pdf_renderer


# ---------------------------------------------------------------------------
# HTML escaping helper
# ---------------------------------------------------------------------------


def _esc(text: str | None) -> str:
    return html_module.escape(str(text) if text is not None else "")


# ---------------------------------------------------------------------------
# Severity classification helpers
# ---------------------------------------------------------------------------

HIGH_SEVERITY_KEYWORDS = [
    "rce",
    "remote code",
    "代码执行",
    "命令执行",
    "command execution",
    "sql注入",
    "sql injection",
    "sqli",
    "sqlmap",
    "认证绕过",
    "auth bypass",
    "登录绕过",
    "未授权",
    "unauthorized",
    "文件上传",
    "file upload",
    "upload",
    "反序列化",
    "deserialization",
    "ssrf",
    "服务器端请求伪造",
    "lfi",
    "本地文件包含",
    "rfi",
    "远程文件包含",
    "权限提升",
    "privilege escalation",
    "提权",
    "硬编码",
    "hardcoded",
    "默认密码",
    "default cred",
    "绕过",
    "bypass",
]

MEDIUM_SEVERITY_KEYWORDS = [
    "xss",
    "跨站脚本",
    "cross-site scripting",
    "信息泄露",
    "信息泄漏",
    "info leak",
    "information disclosure",
    "目录遍历",
    "directory traversal",
    "path traversal",
    "敏感文件",
    "敏感信息",
    "sensitive",
    "版本泄露",
    "版本信息",
    "server version",
    "banner",
    "csrf",
    "跨站请求伪造",
    "idoor",
    " insecure direct object",
    "clickjacking",
    "点击劫持",
    "cors",
    "跨域",
    "robots.txt",
    "git",
    "svn",
    "backup",
    "备份",
    "弱口令",
    "弱密码",
    "weak password",
    "brute force",
    "cookie",
    "session",
    "jwt",
]

LOW_SEVERITY_KEYWORDS = [
    "fingerprint",
    "指纹识别",
    "指纹",
    "http desync",
    "请求走私",
    "smuggling",
    "dns",
    "cdn",
    "waf",
    "http header",
    "响应头",
    "header",
    "ssl",
    "tls",
    "证书",
    "端口扫描",
    "port scan",
    "nmap",
    "目录扫描",
    "dir brute",
    "dirsearch",
    "ffuf",
]

EXPLOIT_KEYWORDS = [
    "curl",
    "wget",
    "python",
    "bash",
    "sh -c",
    "cmd.exe",
    "payload",
    "exploit",
    "poc",
    "proof of concept",
    "union select",
    "or 1=1",
    "';",
    "${",
    "{{",
    "${jndi",
    "base64",
    "eval(",
    "exec(",
    "system(",
    "passthru(",
    "shell_exec(",
    "flag{",
    "flag:",
    "ctf{",
    "root",
    "admin",
    "password",
]

SAFE_TEST_KEYWORDS = [
    "未发现",
    "not found",
    "no vulnerability",
    "不存在",
    "filtered",
    "blocked",
    "waf",
    "安全",
    "secure",
    "无法利用",
    "failed",
    "失败",
    "timeout",
    "超时",
]


def _contains_any(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(kw.lower() in low for kw in keywords)


def _guess_severity(task_name: str, task_desc: str, result: str) -> str:
    combined = f"{task_name} {task_desc} {result or ''}"
    if _contains_any(combined, HIGH_SEVERITY_KEYWORDS):
        return "high"
    if _contains_any(combined, MEDIUM_SEVERITY_KEYWORDS):
        return "medium"
    if _contains_any(combined, LOW_SEVERITY_KEYWORDS):
        return "low"
    return "info"


def _looks_like_successful_exploit(result: str) -> bool:
    if not result:
        return False
    return _contains_any(result, EXPLOIT_KEYWORDS)


def _looks_like_safe_test(result: str) -> bool:
    if not result:
        return False
    return _contains_any(result, SAFE_TEST_KEYWORDS)


# ---------------------------------------------------------------------------
# System info extraction from tool messages
# ---------------------------------------------------------------------------


def _extract_system_info(messages: list[dict]) -> dict[str, str]:
    """Heuristically extract target URL, server, tech stack from tool messages."""
    info: dict[str, str] = {}
    all_text = "\n".join(
        str(m.get("content") or m.get("meta") or "")
        for m in messages
        if m.get("role") in ("tool", "event", "assistant")
    )

    # Target URL from session query or http_request results
    url_match = re.search(r"https?://[^\s\"'<>\)]+", all_text)
    if url_match:
        info["target_url"] = url_match.group(0)

    # Server header
    server_match = re.search(r"[Ss]erver:\s*([^\r\n]+)", all_text)
    if server_match:
        info["web_server"] = server_match.group(1).strip()

    # X-Powered-By
    powered_match = re.search(r"[Xx]-[Pp]owered-[Bb]y:\s*([^\r\n]+)", all_text)
    if powered_match:
        info["powered_by"] = powered_match.group(1).strip()

    # PHP version
    php_match = re.search(r"PHP[/\s]([\d.]+)", all_text)
    if php_match:
        info["php_version"] = php_match.group(1)

    # Framework hints
    framework_hints = {
        "ThinkPHP": ["thinkphp", "think"],
        "Laravel": ["laravel"],
        "Django": ["django", "wsgi"],
        "Spring": ["spring", "java"],
        "Express": ["express", "node.js", "nodejs"],
        "Flask": ["flask"],
        "ASP.NET": ["asp.net", "iis", "microsoft-iis"],
    }
    for fw, kws in framework_hints.items():
        if _contains_any(all_text, kws):
            info["framework"] = fw
            break

    # Architecture / URL rewrite
    if "index.php" in all_text and re.search(r"index\.php/[^\s\"']+", all_text):
        info["architecture"] = "URL重写 (index.php/$1)"

    return info


def _extract_endpoints(messages: list[dict]) -> list[dict]:
    """Extract API endpoints from HTTP-related tool outputs."""
    endpoints: list[dict] = []
    seen = set()
    all_text = "\n".join(
        str(m.get("content") or "")
        for m in messages
        if m.get("role") == "tool"
        and m.get("tool_name") in ("http_request", "fetch_url", "curl")
    )
    # Simple URL path extraction
    for m in re.finditer(
        r"(GET|POST|PUT|DELETE|PATCH)\s+([/\w._-]+(?:\?[^\s\"']+)?)", all_text
    ):
        path = m.group(2)
        if path not in seen:
            seen.add(path)
            endpoints.append({"method": m.group(1), "path": path, "note": ""})
    # Fallback: extract any /path/to/file.html patterns
    for m in re.finditer(
        r"(/[\w./_-]+\.(?:php|html|jsp|asp|aspx|json|api|xml))", all_text
    ):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            endpoints.append({"method": "", "path": path, "note": ""})
    return endpoints[:30]  # cap to avoid noise


# ---------------------------------------------------------------------------
# Report data builder
# ---------------------------------------------------------------------------


class ReportData:
    def __init__(
        self,
        session: dict,
        tasks: list[dict],
        messages: list[dict],
        graph_text: str,
        report_record: Optional[dict] = None,
    ):
        self.session = session
        self.tasks = tasks
        self.messages = messages
        self.graph_text = graph_text

        self.system_info = _extract_system_info(messages)
        self.endpoints = _extract_endpoints(messages)

        # Model-submitted report (from submit_report tool call)
        self.model_markdown: Optional[str] = None
        self.model_summary: dict[str, Any] = {}
        if report_record:
            self.model_markdown = report_record.get("content_markdown")
            self.model_summary = report_record.get("summary_fields") or {}

        # Build vulnerability list from completed tasks with interesting results
        self.vulnerabilities: list[dict] = []
        self.safe_tests: list[dict] = []
        self.payloads: list[dict] = []
        self.key_findings: list[str] = []

        for t in tasks:
            name = t.get("name", "")
            desc = t.get("description", "")
            result = t.get("result") or ""
            findings = t.get("key_findings") or []
            notes = t.get("execution_notes") or []
            status = t.get("status", "")

            # Collect key findings
            for f in findings:
                if f and f not in self.key_findings:
                    self.key_findings.append(f)

            # Identify successful exploits / payloads
            if status == "completed" and result and len(result.strip()) > 10:
                if _looks_like_successful_exploit(result):
                    self.payloads.append(
                        {
                            "task_name": name,
                            "task_id": t.get("id", ""),
                            "payload": result.strip(),
                            "severity": _guess_severity(name, desc, result),
                        }
                    )

            # Classify vulnerability vs safe test
            if status == "completed":
                if _looks_like_safe_test(result):
                    self.safe_tests.append(
                        {
                            "name": name,
                            "result": "未发现漏洞",
                            "note": result.strip()[:200] if result else "",
                        }
                    )
                elif result and len(result.strip()) > 20:
                    # Looks like a finding
                    sev = _guess_severity(name, desc, result)
                    if sev in ("high", "medium", "low"):
                        self.vulnerabilities.append(
                            {
                                "name": name,
                                "description": desc,
                                "severity": sev,
                                "result": result.strip(),
                                "task_id": t.get("id", ""),
                                "findings": findings,
                            }
                        )
            elif status == "failed":
                self.safe_tests.append(
                    {
                        "name": name,
                        "result": "测试失败/未发现",
                        "note": result.strip()[:200] if result else "",
                    }
                )

        # Sort vulnerabilities by severity
        severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        self.vulnerabilities.sort(key=lambda v: severity_order.get(v["severity"], 99))

        # Recommendations
        self.recommendations: list[str] = []
        for v in self.vulnerabilities:
            if v["severity"] == "high":
                self.recommendations.append(
                    f"[{v['name']}] 已确认高危漏洞，建议立即修复并重新验证。"
                )
            elif v["severity"] == "medium":
                self.recommendations.append(
                    f"[{v['name']}] 存在中危风险，建议在下一个迭代周期内处理。"
                )
        if self.system_info.get("php_version") and self.system_info[
            "php_version"
        ].startswith("5."):
            self.recommendations.append(
                f"PHP {self.system_info['php_version']} 已停止维护，存在已知CVE漏洞，建议升级。"
            )

    def risk_summary(self) -> str:
        # Prefer model-submitted summary if available
        if self.model_summary:
            mc = self.model_summary
            target_str = mc.get("target", "")
            vuln_count = mc.get("vuln_count", 0)
            max_sev = mc.get("max_severity", "Info")
            total_tasks = len(self.tasks)
            completed = sum(1 for t in self.tasks if t.get("status") == "completed")
            lines = [
                f"测试目标: {target_str}",
                f"共执行 {total_tasks} 个任务，{completed} 个已完成。",
                f"发现漏洞 {vuln_count} 个，最高严重级别: {max_sev}。",
            ]
            if max_sev.lower() == "high":
                lines.append("存在高危漏洞，系统面临严重安全风险，建议立即采取修复措施。")
            elif max_sev.lower() == "medium":
                lines.append("存在中危漏洞，建议尽快修复以降低安全风险。")
            else:
                lines.append("未发现明显高危漏洞，但建议持续进行安全监测。")
            return "\n".join(lines)
        # Fallback: compute from auto-extracted vulnerabilities
        high = sum(1 for v in self.vulnerabilities if v["severity"] == "high")
        medium = sum(1 for v in self.vulnerabilities if v["severity"] == "medium")
        low = sum(1 for v in self.vulnerabilities if v["severity"] == "low")
        total_tasks = len(self.tasks)
        completed = sum(1 for t in self.tasks if t.get("status") == "completed")
        failed = sum(1 for t in self.tasks if t.get("status") == "failed")
        lines = [
            f"本次渗透测试共执行 {total_tasks} 个任务，其中 {completed} 个已完成，{failed} 个失败。",
            f"发现漏洞 {len(self.vulnerabilities)} 个：高危 {high} 个，中危 {medium} 个，低危 {low} 个。",
        ]
        if high > 0:
            lines.append("存在高危漏洞，系统面临严重安全风险，建议立即采取修复措施。")
        elif medium > 0:
            lines.append("存在中危漏洞，建议尽快修复以降低安全风险。")
        else:
            lines.append("未发现明显高危漏洞，但建议持续进行安全监测。")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report builder
# ---------------------------------------------------------------------------

_SEVERITY_LABELS = {"high": "高危", "medium": "中危", "low": "低危", "info": "信息"}
_SEVERITY_COLORS = {
    "high": "#dc3545",
    "medium": "#ff8800",
    "low": "#ffc107",
    "info": "#6c757d",
}
_SEVERITY_BG = {
    "high": "#f8d7da",
    "medium": "#fff3cd",
    "low": "#d1ecf1",
    "info": "#e2e3e5",
}


def _badge(severity: str) -> str:
    label = _SEVERITY_LABELS.get(severity, severity.upper())
    color = _SEVERITY_COLORS.get(severity, "#6c757d")
    return f'<span class="badge" style="background:{color}">{label}</span>'


def _build_cover(report_data: ReportData) -> str:
    title = _esc(report_data.session.get("title") or "未命名目标")
    sid = _esc(report_data.session.get("id", ""))
    mode = _esc(report_data.session.get("mode", ""))
    created = _esc(report_data.session.get("created_at") or "")
    max_sev = ""
    if report_data.model_summary:
        max_sev = report_data.model_summary.get("max_severity", "")
    risk_html = ""
    if max_sev:
        color = _SEVERITY_COLORS.get(max_sev.lower(), "#6c757d")
        risk_html = f'<div class="cover-risk" style="color:{color}">风险评级: {_esc(max_sev)}</div>'

    return f"""
<div class="cover">
  <div class="cover-icon">&#128737;</div>
  <div class="cover-title">渗透测试报告</div>
  <div class="cover-subtitle">{title}</div>
  <div class="cover-meta">
    <p><strong>会话 ID:</strong> {sid}</p>
    <p><strong>模式:</strong> {mode}</p>
    {f'<p><strong>创建时间:</strong> {created}</p>' if created else ''}
  </div>
  {risk_html}
</div>
"""


def _build_basic_info(report_data: ReportData) -> str:
    si = report_data.system_info
    model_target = report_data.model_summary.get("target") if report_data.model_summary else None
    target = model_target or si.get("target_url") or "未识别"

    rows: list[tuple[str, str]] = [
        ("测试目标", _esc(target)),
        ("会话名称", _esc(report_data.session.get("title") or "未命名")),
    ]
    if si.get("web_server"):
        rows.append(("Web 服务器", _esc(si["web_server"])))
    if si.get("powered_by"):
        rows.append(("技术栈", _esc(si["powered_by"])))
    if si.get("php_version"):
        rows.append(("PHP 版本", _esc(si["php_version"])))
    if si.get("framework"):
        rows.append(("框架", _esc(si["framework"])))
    if si.get("architecture"):
        rows.append(("架构", _esc(si["architecture"])))
    rows.append(("模式", _esc(report_data.session.get("mode", ""))))
    rows.append(("状态", _esc(report_data.session.get("status", ""))))

    rows_html = "\n".join(
        f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>" for k, v in rows
    )

    services_html = ""
    if report_data.model_summary:
        services = report_data.model_summary.get("services_discovered") or []
        if services:
            svc_rows = "\n".join(f"<tr><td>{_esc(s)}</td></tr>" for s in services)
            services_html = f"""
<h2>发现的服务</h2>
<table class="stat-table">
  <thead><tr><th>服务 (IP:Port)</th></tr></thead>
  <tbody>{svc_rows}</tbody>
</table>
"""

    return f"""
<div class="page-break">
  <h1>基本信息</h1>
  <table class="info-table">
    <tbody>{rows_html}</tbody>
  </table>
  {services_html}
</div>
"""


def _build_risk_summary(report_data: ReportData) -> str:
    findings_html = ""
    if report_data.key_findings:
        items = "\n".join(
            f'<li>{_esc(f)}</li>' for f in report_data.key_findings
        )
        findings_html = f"""
<h2>关键发现</h2>
<ul>{items}</ul>
"""

    stats_html = ""
    model_vulns = report_data.model_summary.get("vulnerabilities") or [] if report_data.model_summary else []
    if model_vulns:
        sev_counts = {"High": 0, "Medium": 0, "Low": 0, "Info": 0}
        for mv in model_vulns:
            s = mv.get("severity", "Info")
            sev_counts[s] = sev_counts.get(s, 0) + 1
        stats_rows = ""
        for sev, count in sev_counts.items():
            if count > 0:
                label = _SEVERITY_LABELS.get(sev.lower(), sev)
                stats_rows += f'<tr><td>{label}</td><td>{count}</td></tr>\n'
        if stats_rows:
            stats_html = f"""
<h2>漏洞统计</h2>
<table class="stat-table">
  <thead><tr><th>严重程度</th><th>数量</th></tr></thead>
  <tbody>{stats_rows}</tbody>
</table>
"""

    recommendations_html = ""
    if report_data.recommendations:
        recs = "\n".join(
            f'<div class="recommendation">{_esc(r)}</div>' for r in report_data.recommendations
        )
        recommendations_html = f"""
<h2>修复建议</h2>
{recs}
"""

    return f"""
<div class="page-break">
  <h1>风险总结</h1>
  <div class="section">
    <div style="white-space:pre-wrap; font-family:inherit;">{_esc(report_data.risk_summary())}</div>
  </div>
  {findings_html}
  {stats_html}
  {recommendations_html}
</div>
"""


def _build_attack_graph(report_data: ReportData) -> str:
    task_rows = ""
    for idx, t in enumerate(report_data.tasks, 1):
        status = t.get("status", "")
        name = t.get("name", "")
        task_rows += f'<tr><td>{idx}</td><td>{_esc(name[:60])}</td><td>{_esc(status.upper())}</td></tr>\n'

    return f"""
<div class="page-break">
  <h1>攻击图谱</h1>
  <p>以下为本次渗透测试的任务执行链路，展示了各任务的依赖关系和执行顺序。</p>
  <div class="graph-block">{_esc(report_data.graph_text or "无任务数据")}</div>

  <h2>任务执行摘要</h2>
  <table class="stat-table">
    <thead><tr><th>#</th><th>任务</th><th>状态</th></tr></thead>
    <tbody>{task_rows}</tbody>
  </table>
</div>
"""


def _build_ai_report(report_data: ReportData) -> str:
    model_vulns = []
    if report_data.model_summary:
        model_vulns = report_data.model_summary.get("vulnerabilities") or []

    vuln_table_html = ""
    vuln_cards_html = ""

    if model_vulns:
        vuln_rows = ""
        for idx, mv in enumerate(model_vulns, 1):
            vuln_rows += (
                f'<tr>'
                f'<td>{idx}</td>'
                f'<td>{_esc(mv.get("name", "")[:50])}</td>'
                f'<td>{_esc(mv.get("service", "")[:30])}</td>'
                f'<td>{_badge(mv.get("severity", "Info").lower())}</td>'
                f'</tr>\n'
            )
        vuln_table_html = f"""
<h2>漏洞概览</h2>
<table class="stat-table">
  <thead><tr><th>#</th><th>漏洞名称</th><th>服务</th><th>严重程度</th></tr></thead>
  <tbody>{vuln_rows}</tbody>
</table>
"""

        for idx, mv in enumerate(model_vulns, 1):
            name = mv.get("name", f"漏洞 {idx}")
            sev = mv.get("severity", "Info").lower()
            sev_label = _SEVERITY_LABELS.get(sev, sev)
            bg = _SEVERITY_BG.get(sev, "#e2e3e5")

            detail_rows = []
            if mv.get("service"):
                detail_rows.append(("服务", mv["service"]))
            if mv.get("url"):
                detail_rows.append(("URL", mv["url"]))
            if mv.get("type"):
                detail_rows.append(("类型", mv["type"]))
            detail_rows.append(("严重程度", sev_label))
            if mv.get("remediation"):
                detail_rows.append(("修复建议", mv["remediation"]))

            details = "\n".join(
                f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k, v in detail_rows
            )

            payload_html = ""
            if mv.get("payload"):
                payload_html = f"""
<p><strong>Payload / PoC:</strong></p>
<pre>{_esc(mv["payload"])}</pre>
"""

            vuln_cards_html += f"""
<div class="vuln-card" style="border-left: 4px solid {_SEVERITY_COLORS.get(sev, '#6c757d')}; background: {bg};">
  <h3>{idx}. [{sev_label.upper()}] {_esc(name)}</h3>
  <table class="info-table">
    <tbody>{details}</tbody>
  </table>
  {payload_html}
</div>
"""

    markdown_html = ""
    if report_data.model_markdown:
        md = markdown.markdown(
            report_data.model_markdown,
            extensions=["tables", "fenced_code"],
        )
        # Wrap tables for break-inside styling
        md = md.replace("<table>", '<table class="stat-table">')
        markdown_html = f"""
<h2>详细报告</h2>
<div class="markdown-content">
{md}
</div>
"""

    return f"""
<div class="page-break">
  <h1>AI 渗透测试报告</h1>
  <p>以下为 AI 引擎在任务完成后自动生成的详细渗透测试报告，包含漏洞详情、利用证据、Payload、修复建议等完整内容。</p>
  {vuln_table_html}
  {vuln_cards_html}
  {markdown_html}
</div>
"""


def _build_styles() -> str:
    return """
<style>
  /* ---------- Base ---------- */
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 0;
    font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.6;
    color: #333;
  }

  /* ---------- Cover ---------- */
  .cover {
    text-align: center;
    padding-top: 120px;
    page-break-after: always;
  }
  .cover-icon { font-size: 64pt; margin-bottom: 30px; }
  .cover-title { font-size: 32pt; font-weight: bold; color: #222; margin-bottom: 16px; }
  .cover-subtitle { font-size: 16pt; color: #555; margin-bottom: 40px; }
  .cover-meta { font-size: 11pt; color: #666; line-height: 2.2; }
  .cover-meta p { margin: 4px 0; }
  .cover-risk { font-size: 18pt; font-weight: bold; margin-top: 30px; }

  /* ---------- Typography ---------- */
  h1 {
    font-size: 20pt;
    color: #dc3545;
    border-bottom: 2px solid #dc3545;
    padding-bottom: 8px;
    margin-top: 0;
    page-break-after: avoid;
  }
  h2 {
    font-size: 14pt;
    color: #333;
    margin-top: 24px;
    page-break-after: avoid;
  }
  h3 {
    font-size: 12pt;
    color: #444;
    margin-top: 16px;
    page-break-after: avoid;
  }
  p { margin: 8px 0; }

  /* ---------- Layout ---------- */
  .page-break { page-break-before: always; }
  .section { margin-bottom: 20px; }

  /* ---------- Tables ---------- */
  .info-table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
  }
  .info-table td {
    border: 1px solid #ddd;
    padding: 8px 12px;
  }
  .info-table td:first-child {
    background: #f8f9fa;
    font-weight: bold;
    width: 30%;
    color: #444;
  }

  .stat-table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    break-inside: avoid;
  }
  .stat-table th {
    background: #dc3545;
    color: white;
    font-weight: bold;
    padding: 8px 12px;
    text-align: left;
    border: 1px solid #dc3545;
  }
  .stat-table td {
    border: 1px solid #ddd;
    padding: 8px 12px;
  }
  .stat-table tr:nth-child(even) { background: #f8f9fa; }

  /* ---------- Badges ---------- */
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 9pt;
    font-weight: bold;
    color: white;
  }

  /* ---------- Code ---------- */
  pre {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 12px;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", monospace;
    font-size: 9pt;
    white-space: pre-wrap;
    word-break: break-all;
    margin: 10px 0;
    break-inside: avoid;
  }
  code {
    background: #f5f5f5;
    padding: 1px 4px;
    border-radius: 3px;
    font-family: "JetBrains Mono", "Fira Code", "Consolas", "Courier New", monospace;
    font-size: 9pt;
  }

  /* ---------- Vulnerability cards ---------- */
  .vuln-card {
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 16px;
    margin: 16px 0;
    break-inside: avoid;
  }
  .vuln-card h3 { margin-top: 0; font-size: 12pt; }

  /* ---------- Graph block ---------- */
  .graph-block {
    background: #f8f9fa;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 12px;
    font-family: "JetBrains Mono", "Consolas", monospace;
    font-size: 9pt;
    white-space: pre-wrap;
    break-inside: avoid;
  }

  /* ---------- Lists ---------- */
  ul, ol { margin: 8px 0; padding-left: 24px; }
  li { margin: 4px 0; }

  /* ---------- Markdown content overrides ---------- */
  .markdown-content h1 { font-size: 16pt; }
  .markdown-content h2 { font-size: 13pt; }
  .markdown-content h3 { font-size: 11pt; }
  .markdown-content pre { break-inside: avoid; }
  .markdown-content table { break-inside: avoid; }

  /* ---------- Recommendations ---------- */
  .recommendation {
    background: #d1ecf1;
    border-left: 4px solid #17a2b8;
    padding: 10px 14px;
    margin: 8px 0;
    break-inside: avoid;
    border-radius: 0 4px 4px 0;
  }
</style>
"""


def render_report_html(report_data: ReportData) -> str:
    """Render a ReportData instance into a complete HTML document."""
    cover = _build_cover(report_data)
    basic_info = _build_basic_info(report_data)
    risk_summary = _build_risk_summary(report_data)
    attack_graph = _build_attack_graph(report_data)
    ai_report = _build_ai_report(report_data)
    styles = _build_styles()

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>渗透测试报告 - {_esc(report_data.session.get("title") or "未命名目标")}</title>
{styles}
</head>
<body>
{cover}
{basic_info}
{risk_summary}
{attack_graph}
{ai_report}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# PDF generation (async)
# ---------------------------------------------------------------------------


_HEADER_TEMPLATE = """<div style="font-size:9px; width:100%; margin:0 auto; padding:0 5mm;">
  <table style="width:100%; border:none;">
    <tr>
      <td style="text-align:left; border:none; color:#888;">Ion 渗透测试报告</td>
      <td style="text-align:right; border:none; color:#888;">第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</td>
    </tr>
  </table>
</div>"""

_FOOTER_TEMPLATE = """<div style="font-size:8px; text-align:center; width:100%; color:#aaa;">
  生成时间: {generated_at}
</div>"""


async def generate_pdf(report_data: ReportData, output_path: str | Path) -> Path:
    """Generate a PDF file from *report_data* and write it to *output_path*.

    Returns the Path to the generated PDF.
    """
    html = render_report_html(report_data)
    renderer = get_pdf_renderer()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = await renderer.render(
        html,
        output_path=output_path,
        margin={"top": "18mm", "bottom": "18mm", "left": "15mm", "right": "15mm"},
        header_template=_HEADER_TEMPLATE,
        footer_template=_FOOTER_TEMPLATE.format(generated_at=generated_at),
    )
    if isinstance(result, Path):
        return result
    # Fallback: write bytes ourselves if render returned bytes
    path = Path(output_path)
    path.write_bytes(result)
    return path
