"""Penetration test report generator.

Produces rich PDF reports from session data (tasks, messages, attack graph).
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from fpdf import FPDF


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
    ):
        self.session = session
        self.tasks = tasks
        self.messages = messages
        self.graph_text = graph_text

        self.system_info = _extract_system_info(messages)
        self.endpoints = _extract_endpoints(messages)

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
# PDF renderer (fpdf2)
# ---------------------------------------------------------------------------


class _PDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self._setup_fonts()

    def _setup_fonts(self) -> None:
        # Try common CJK font paths
        font_paths = [
            # 优先尝试文泉驿微米黑，它在 Linux 下生成 PDF 的兼容性最好
            (
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            ),
            # 其次尝试你的 Noto CJK
            (
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            ),
        ]
        for regular, bold in font_paths:
            if os.path.exists(regular) and os.path.exists(bold):
                self.add_font("NotoSans", "", regular)
                self.add_font("NotoSans", "B", bold)
                self.set_font("NotoSans", "", 11)
                return
        # Fallback to built-in Helvetica (ASCII only)
        self.set_font("Helvetica", "", 11)

    def header(self) -> None:
        if self.page_no() == 1:
            return  # Skip header on cover
        self.set_font("NotoSans", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "Ion 渗透测试报告", align="L")
        self.cell(0, 8, f"第 {self.page_no()} 页", align="R")
        self.ln(8)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("NotoSans", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(
            0,
            10,
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            align="C",
        )

    def chapter_title(self, title: str, level: int = 1) -> None:
        if level == 1:
            self.set_font("NotoSans", "B", 16)
            self.set_text_color(220, 53, 69)
            self.ln(4)
            self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(220, 53, 69)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(4)
        elif level == 2:
            self.set_font("NotoSans", "B", 13)
            self.set_text_color(40, 40, 40)
            self.ln(3)
            self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
            self.ln(1)
        else:
            self.set_font("NotoSans", "B", 11)
            self.set_text_color(60, 60, 60)
            self.ln(2)
            self.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")

    def body_text(self, text: str) -> None:
        self.set_font("NotoSans", "", 10)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def code_block(self, code: str) -> None:
        self.set_fill_color(245, 245, 245)
        self.set_draw_color(220, 220, 220)
        # Use NotoSans for CJK support in code blocks; Courier lacks Unicode
        self.set_font("NotoSans", "", 9)
        self.set_text_color(30, 30, 30)
        wrapped = textwrap.fill(code, width=95)
        self.multi_cell(0, 5, wrapped, border=1, fill=True)
        self.ln(2)

    def severity_badge(self, severity: str) -> None:
        colors = {
            "high": (220, 53, 69),
            "medium": (255, 136, 0),
            "low": (255, 193, 7),
            "info": (108, 117, 125),
        }
        bg = colors.get(severity, colors["info"])
        labels = {
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "信息",
        }
        # Draw rounded-ish rectangle
        self.set_fill_color(*bg)
        self.set_text_color(255, 255, 255)
        self.set_font("NotoSans", "B", 10)
        label = labels.get(severity, severity.upper())
        w = self.get_string_width(label) + 6
        self.cell(w, 7, f"  {label}  ", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(50, 50, 50)

    def info_table(self, rows: list[tuple[str, str]]) -> None:
        col1_w = 45
        col2_w = 145
        self.set_font("NotoSans", "B", 10)
        self.set_fill_color(240, 240, 240)
        for key, val in rows:
            self.cell(col1_w, 7, f"  {key}", border=1, fill=True)
            self.set_font("NotoSans", "", 10)
            self.cell(col2_w, 7, f"  {val}", border=1)
            self.ln(7)
            self.set_font("NotoSans", "B", 10)
        self.ln(2)

    def stat_table(self, headers: list[str], rows: list[list[str]]) -> None:
        col_w = 190 / len(headers)
        self.set_font("NotoSans", "B", 10)
        self.set_fill_color(220, 53, 69)
        self.set_text_color(255, 255, 255)
        for h in headers:
            self.cell(col_w, 8, f"  {h}", border=1, fill=True)
        self.ln(8)
        self.set_text_color(50, 50, 50)
        self.set_font("NotoSans", "", 10)
        for row in rows:
            for cell in row:
                self.cell(col_w, 7, f"  {cell}", border=1)
            self.ln(7)
        self.ln(2)

    def safe_multi_cell(self, h: float, text: str) -> None:
        """multi_cell wrapper that resets x to left margin to avoid width errors."""
        self.set_x(10)
        self.multi_cell(0, h, text)


def generate_pdf(report_data: ReportData) -> bytes:
    pdf = _PDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ---- Cover ----
    pdf.add_page()
    pdf.set_y(80)
    pdf.set_font("NotoSans", "B", 28)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 15, "渗透测试报告", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NotoSans", "", 14)
    pdf.set_text_color(100, 100, 100)
    title = report_data.session.get("title") or "未命名目标"
    pdf.cell(0, 10, title, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("NotoSans", "", 11)
    pdf.cell(
        0,
        8,
        f"会话 ID: {report_data.session.get('id', '')}",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.cell(
        0,
        8,
        f"模式: {report_data.session.get('mode', '')}",
        align="C",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    created = report_data.session.get("created_at") or ""
    if created:
        pdf.cell(0, 8, f"创建时间: {created}", align="C", new_x="LMARGIN", new_y="NEXT")

    # ---- 1. Basic Info ----
    pdf.add_page()
    pdf.chapter_title("基本信息", level=1)
    rows: list[tuple[str, str]] = []
    si = report_data.system_info
    rows.append(("目标 URL", si.get("target_url") or "未识别"))
    rows.append(("系统名称", report_data.session.get("title") or "未命名"))
    if si.get("web_server"):
        rows.append(("Web 服务器", si["web_server"]))
    if si.get("powered_by"):
        rows.append(("技术栈", si["powered_by"]))
    if si.get("php_version"):
        rows.append(("PHP 版本", si["php_version"]))
    if si.get("framework"):
        rows.append(("框架", si["framework"]))
    if si.get("architecture"):
        rows.append(("架构", si["architecture"]))
    rows.append(("会话模式", report_data.session.get("mode", "")))
    rows.append(("会话状态", report_data.session.get("status", "")))
    pdf.info_table(rows)

    # ---- 2. Risk Summary ----
    pdf.chapter_title("风险总结", level=1)
    pdf.body_text(report_data.risk_summary())

    # Key findings
    if report_data.key_findings:
        pdf.chapter_title("关键发现", level=2)
        for i, finding in enumerate(report_data.key_findings, 1):
            pdf.set_font("NotoSans", "B", 10)
            pdf.cell(0, 6, f"{i}. {finding[:120]}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    # ---- 3. Vulnerabilities ----
    pdf.add_page()
    pdf.chapter_title("发现的漏洞", level=1)
    if not report_data.vulnerabilities:
        pdf.body_text("未发现明显的可利用漏洞。")
    else:
        for idx, vuln in enumerate(report_data.vulnerabilities, 1):
            sev_label = {
                "high": "高危",
                "medium": "中危",
                "low": "低危",
                "info": "信息",
            }.get(vuln["severity"], vuln["severity"])
            status_icon = "[已验证]" if vuln.get("result") else "[待验证]"
            pdf.chapter_title(
                f"{idx}. [{sev_label.upper()}] {vuln['name']} {status_icon}", level=2
            )
            pdf.info_table(
                [
                    (
                        "漏洞类型",
                        vuln["description"][:80] if vuln["description"] else "未分类",
                    ),
                    ("严重程度", sev_label),
                    ("任务 ID", vuln.get("task_id", "")),
                ]
            )
            if vuln.get("findings"):
                pdf.set_font("NotoSans", "B", 10)
                pdf.cell(0, 6, "关键发现:", new_x="LMARGIN", new_y="NEXT")
                for f in vuln["findings"]:
                    pdf.set_font("NotoSans", "", 10)
                    pdf.safe_multi_cell(5, f"  • {f}")
                pdf.ln(1)
            if vuln.get("result"):
                pdf.set_font("NotoSans", "B", 10)
                pdf.cell(0, 6, "详细结果 / Payload:", new_x="LMARGIN", new_y="NEXT")
                pdf.code_block(vuln["result"][:1500])

    # ---- 4. Safe tests ----
    if report_data.safe_tests:
        pdf.add_page()
        pdf.chapter_title("已测试但未发现漏洞的项目", level=1)
        headers = ["测试项目", "结果", "说明"]
        rows = []
        for st in report_data.safe_tests[:40]:
            rows.append(
                [
                    st["name"][:30],
                    st["result"][:20],
                    st["note"][:50] if st["note"] else "—",
                ]
            )
        pdf.stat_table(headers, rows)

    # ---- 5. Payloads ----
    if report_data.payloads:
        pdf.add_page()
        pdf.chapter_title("利用成功的 Payload", level=1)
        for idx, p in enumerate(report_data.payloads, 1):
            sev_label = {
                "high": "高危",
                "medium": "中危",
                "low": "低危",
                "info": "信息",
            }.get(p["severity"], p["severity"])
            pdf.chapter_title(f"{idx}. [{sev_label}] {p['task_name']}", level=2)
            pdf.code_block(p["payload"][:2000])

    # ---- 6. Endpoints ----
    if report_data.endpoints:
        pdf.add_page()
        pdf.chapter_title("发现的 API 端点 / 路径", level=1)
        headers = ["方法", "路径", "备注"]
        rows = [
            [e.get("method", ""), e["path"], e.get("note", "")]
            for e in report_data.endpoints[:50]
        ]
        pdf.stat_table(headers, rows)

    # ---- 7. Attack Chain ----
    pdf.add_page()
    pdf.chapter_title("利用链路 / 攻击图谱", level=1)
    pdf.body_text("以下为本次渗透测试的任务执行链路（按依赖关系排序）:")
    pdf.ln(2)
    pdf.code_block(report_data.graph_text or "无任务数据")

    # Task chain detail
    pdf.chapter_title("任务执行详情", level=2)
    for idx, t in enumerate(report_data.tasks, 1):
        status = t.get("status", "")
        name = t.get("name", "")
        result = t.get("result") or ""
        pdf.set_font("NotoSans", "B", 10)
        pdf.cell(
            0, 6, f"{idx}. [{status.upper()}] {name}", new_x="LMARGIN", new_y="NEXT"
        )
        if result:
            pdf.set_font("NotoSans", "", 9)
            snippet = result.strip()[:300].replace("\n", " ")
            pdf.safe_multi_cell(5, f"   结果: {snippet}")
        pdf.ln(1)

    # ---- 8. Recommendations ----
    pdf.add_page()
    pdf.chapter_title("渗透建议", level=1)
    if report_data.recommendations:
        for rec in report_data.recommendations:
            pdf.set_font("NotoSans", "", 10)
            pdf.cell(0, 6, f"• {rec}", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.body_text("暂无具体建议。")

    # ---- 9. Stats ----
    pdf.chapter_title("漏洞统计", level=1)
    high = sum(1 for v in report_data.vulnerabilities if v["severity"] == "high")
    medium = sum(1 for v in report_data.vulnerabilities if v["severity"] == "medium")
    low = sum(1 for v in report_data.vulnerabilities if v["severity"] == "low")
    safe = len(report_data.safe_tests)
    headers = ["严重程度", "数量"]
    rows = [
        ["高危", str(high)],
        ["中危", str(medium)],
        ["低危", str(low)],
        ["安全测试通过", str(safe)],
    ]
    pdf.stat_table(headers, rows)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
