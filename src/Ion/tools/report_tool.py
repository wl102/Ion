"""Submit final penetration test report tool.

Persists the model's final markdown report + structured summary to the
database via ``ReportRecord`` so the PDF download endpoint can assemble
a rich report without re-parsing the conversation history.
"""

from __future__ import annotations

import json
import logging

from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def _submit_report(summary_fields: dict, content_markdown: str) -> str:
    """Persist the final penetration test report to the database.

    Uses ``_current_task_manager_ctx`` from ``task_tool`` to resolve the
    active session's ``PersistentTaskManager``, which carries ``session_id``
    and a ``_get_db()`` database provider.
    """
    from Ion.tools.task_tool import _current_task_manager_ctx

    tm = _current_task_manager_ctx.get()
    if tm is None:
        return tool_error("No active task manager context")

    session_id = getattr(tm, "session_id", None)
    if not session_id:
        return tool_error("Task manager does not provide session_id")

    get_db = getattr(tm, "_get_db", None)
    if not get_db:
        return tool_error("Task manager does not provide database access")
    db_provider = get_db()

    from Ion.db.models import ReportRecord

    try:
        summary_json = json.dumps(summary_fields, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        return tool_error(f"Invalid summary_fields: {e}")

    try:
        with next(db_provider.get_session()) as sess:
            existing = (
                sess.query(ReportRecord)
                .filter_by(session_id=session_id)
                .first()
            )
            if existing:
                existing.summary_fields = summary_json
                existing.content_markdown = content_markdown
            else:
                record = ReportRecord(
                    session_id=session_id,
                    summary_fields=summary_json,
                    content_markdown=content_markdown,
                )
                sess.add(record)
            sess.commit()
    except Exception as e:
        logger.warning("submit_report persist failed: %s", e, exc_info=True)
        return tool_error(f"Failed to persist report: {e}")

    return tool_result(success=True, message="Report saved successfully")


# ---------------------------------------------------------------------------
# Schema (OpenAI function-calling format)
# ---------------------------------------------------------------------------

SUBMIT_REPORT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_report",
        "description": (
            "Submit the final penetration test report. "
            "Call this ONCE at the end of the mission after ALL tasks are complete. "
            "The report will be persisted and included in the downloadable PDF."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary_fields": {
                    "type": "object",
                    "description": "Structured summary of findings",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Target IP or hostname",
                        },
                        "vuln_count": {
                            "type": "integer",
                            "description": "Total number of vulnerabilities found",
                        },
                        "max_severity": {
                            "type": "string",
                            "enum": ["High", "Medium", "Low", "Info"],
                            "description": "Maximum severity level",
                        },
                        "services_discovered": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of discovered services (IP:Port)",
                        },
                        "vulnerabilities": {
                            "type": "array",
                            "description": "List of vulnerabilities found",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Vulnerability name",
                                    },
                                    "service": {
                                        "type": "string",
                                        "description": "Affected service (IP:Port)",
                                    },
                                    "url": {
                                        "type": "string",
                                        "description": "Full URL of the affected endpoint",
                                    },
                                    "severity": {
                                        "type": "string",
                                        "enum": [
                                            "High",
                                            "Medium",
                                            "Low",
                                            "Info",
                                        ],
                                        "description": "Severity level",
                                    },
                                    "type": {
                                        "type": "string",
                                        "description": "Vulnerability type (SQLi, XSS, RCE, LFI, SSRF, IDOR, etc.)",
                                    },
                                    "payload": {
                                        "type": "string",
                                        "description": "Exact payload or exploit command used",
                                    },
                                    "remediation": {
                                        "type": "string",
                                        "description": "Recommended fix",
                                    },
                                },
                                "required": ["name", "service", "severity"],
                            },
                        },
                    },
                    "required": ["target", "vuln_count", "max_severity"],
                },
                "content_markdown": {
                    "type": "string",
                    "description": (
                        "Full penetration test report in Markdown format "
                        "(can be thousands of characters). "
                        "Must include: executive summary, methodology, "
                        "detailed findings for each vulnerability with evidence, "
                        "attack chain, and recommendations."
                    ),
                },
            },
            "required": ["summary_fields", "content_markdown"],
        },
    },
}

# ---------------------------------------------------------------------------
# Registration (side-effect at import time)
# ---------------------------------------------------------------------------

registry.register(
    name="submit_report",
    toolset="report",
    schema=SUBMIT_REPORT_SCHEMA,
    handler=_submit_report,
    is_async=False,
    description=(
        "Submit the final penetration test report with structured summary "
        "and full markdown report content."
    ),
    emoji="📄",
    max_result_size_chars=2000,
)
