"""Playwright-based browser execution tool.

Acts as the "verifier" layer in the HTTP→Browser two-tier scanning architecture:
HTTP tools find suspected vulnerabilities, this tool confirms them in a real
browser runtime where DOM, JS execution, postMessage, CSP, and SPA framework
behaviour are observable.

Each call launches a fresh chromium context, runs an ordered action list,
captures every HTTP request/response (including XHR/fetch/WebSocket), records
hits on XSS sinks via a JS prelude, and returns structured evidence.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults / limits
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 1024          # per-response body cap (bytes)
_MAX_NETWORK_ENTRIES = 100      # max captured entries returned in result
_MAX_SINK_EVENTS = 100          # max XSS sink events returned
_MAX_CONSOLE_MSGS = 50          # max console messages returned
_MAX_PAGE_ERRORS = 20           # max page errors returned
_MAX_WEBSOCKET_FRAMES = 50
_DEFAULT_NAV_TIMEOUT_MS = 30_000
_DEFAULT_ACTION_TIMEOUT_MS = 10_000
_SCREENSHOT_DIR = Path(os.getenv("ION_BROWSER_ARTIFACT_DIR", "/tmp/ion_browser"))
_MODEL_SUPPORTS_VISION = os.getenv("MODEL_SUPPORTS_VISION", "").lower() in (
    "1",
    "true",
    "yes",
)


# ---------------------------------------------------------------------------
# JS prelude: wrap common XSS sinks and record hits onto window.__ion_sinks
# and also flush to console so they survive page navigations.
# ---------------------------------------------------------------------------

_SINK_HOOK_SCRIPT = r"""
(() => {
  if (window.__ion_sinks_installed) return;
  window.__ion_sinks_installed = true;
  window.__ion_sinks = [];

  const _flush = (entry) => {
    try {
      console.log('__ION_SINK__' + JSON.stringify(entry));
    } catch (e) {}
  };

  const record = (sink, value, extra) => {
    try {
      const entry = {
        sink,
        value: typeof value === 'string' ? value.slice(0, 2048) : String(value).slice(0, 2048),
        url: location.href,
        ts: Date.now(),
      };
      if (extra) entry.extra = extra;
      window.__ion_sinks.push(entry);
      _flush(entry);
    } catch (e) {}
  };

  // innerHTML / outerHTML setters
  for (const prop of ['innerHTML', 'outerHTML']) {
    const desc = Object.getOwnPropertyDescriptor(Element.prototype, prop);
    if (desc && desc.set) {
      const orig = desc.set;
      Object.defineProperty(Element.prototype, prop, {
        configurable: true,
        get: desc.get,
        set: function (v) { record(prop, v, this.tagName); return orig.call(this, v); },
      });
    }
  }

  // insertAdjacentHTML — another common sink
  const origIAH = Element.prototype.insertAdjacentHTML;
  if (origIAH) {
    Element.prototype.insertAdjacentHTML = function (pos, html) {
      record('insertAdjacentHTML', html, this.tagName + ':' + pos);
      return origIAH.call(this, pos, html);
    };
  }

  // document.write / writeln
  for (const m of ['write', 'writeln']) {
    const orig = document[m];
    if (orig) {
      document[m] = function (...args) { record('document.' + m, args.join('')); return orig.apply(this, args); };
    }
  }

  // eval
  const origEval = window.eval;
  window.eval = function (s) { record('eval', s); return origEval.call(this, s); };

  // Function constructor
  const OrigFunction = window.Function;
  window.Function = new Proxy(OrigFunction, {
    construct(target, args) { record('Function', args.join(' | ')); return new target(...args); },
    apply(target, thisArg, args) { record('Function', args.join(' | ')); return target.apply(thisArg, args); },
  });

  // setTimeout / setInterval with string arg
  for (const m of ['setTimeout', 'setInterval']) {
    const orig = window[m];
    window[m] = function (h, ...rest) { if (typeof h === 'string') record(m + '(string)', h); return orig.call(this, h, ...rest); };
  }

  // location assignment / href setter
  const origAssign = window.location.assign;
  if (origAssign) window.location.assign = function (u) { record('location.assign', u); return origAssign.call(this, u); };

  // Element.setAttribute on event handlers / src / href
  const origSetAttr = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    const lower = String(name).toLowerCase();
    if (lower.startsWith('on') || lower === 'src' || lower === 'href' || lower === 'srcdoc' || lower === 'formaction') {
      record('setAttribute(' + lower + ')', value, this.tagName);
    }
    return origSetAttr.call(this, name, value);
  };

  // Track dialog (alert/confirm/prompt) — strong XSS signal
  for (const m of ['alert', 'confirm', 'prompt']) {
    const orig = window[m];
    window[m] = function (...args) { record('dialog.' + m, args[0] !== undefined ? args[0] : ''); return orig ? orig.apply(this, args) : undefined; };
  }
})();
"""


# ---------------------------------------------------------------------------
# Network capture helpers
# ---------------------------------------------------------------------------


def _safe_decode(data: bytes | None) -> str:
    if not data:
        return ""
    truncated = data[:_MAX_BODY_BYTES]
    text = truncated.decode("utf-8", errors="replace")
    if len(data) > _MAX_BODY_BYTES:
        text += f"\n...[truncated, total {len(data)} bytes]"
    return text


def _serialize_request(request) -> dict:
    headers = {}
    try:
        headers = dict(request.headers)
    except Exception:
        pass
    return {
        "url": request.url,
        "method": request.method,
        "resource_type": getattr(request, "resource_type", ""),
        "headers": headers,
    }


def _serialize_request_with_body(request) -> dict:
    entry = _serialize_request(request)
    post = ""
    try:
        raw = request.post_data_buffer
        if raw is not None:
            post = _safe_decode(raw)
    except Exception:
        pass
    entry["post_data"] = post
    return entry


def _dedupe_sinks(sinks: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for s in sinks:
        key = (s.get("sink"), s.get("value"), s.get("url"), s.get("ts"))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Action runner
# ---------------------------------------------------------------------------


async def _run_action(page, action: dict, action_timeout_ms: int) -> dict:
    """Execute a single action on the page; return {ok, ...action result}."""
    atype = action.get("type", "").lower()

    if atype == "navigate":
        url = action.get("url")
        if not url:
            return {"type": atype, "ok": False, "error": "missing url"}
        wait_until = action.get("wait_until", "load")
        nav_timeout = action.get("timeout_ms", _DEFAULT_NAV_TIMEOUT_MS)
        try:
            resp = await page.goto(url, wait_until=wait_until, timeout=nav_timeout)
            return {
                "type": atype,
                "ok": True,
                "url": page.url,
                "status": resp.status if resp else None,
            }
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e), "url": page.url}

    if atype == "wait":
        selector = action.get("selector")
        if not selector:
            return {"type": atype, "ok": False, "error": "missing selector"}
        try:
            await page.wait_for_selector(
                selector,
                timeout=action_timeout_ms,
                state=action.get("state", "visible"),
            )
            return {"type": atype, "ok": True, "selector": selector}
        except Exception as e:
            return {"type": atype, "ok": False, "selector": selector, "error": _sanitize_error(e)}

    if atype == "wait_for_load":
        try:
            await page.wait_for_load_state(
                action.get("state", "networkidle"),
                timeout=action_timeout_ms,
            )
            return {"type": atype, "ok": True}
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e)}

    if atype == "wait_ms":
        ms = int(action.get("ms", 1000))
        await page.wait_for_timeout(ms)
        return {"type": atype, "ok": True, "ms": ms}

    if atype == "click":
        selector = action.get("selector")
        if not selector:
            return {"type": atype, "ok": False, "error": "missing selector"}
        try:
            await page.click(selector, timeout=action_timeout_ms)
            return {"type": atype, "ok": True, "selector": selector}
        except Exception as e:
            return {"type": atype, "ok": False, "selector": selector, "error": _sanitize_error(e)}

    if atype in ("type", "fill"):
        selector = action.get("selector")
        text = action.get("text", "")
        if not selector:
            return {"type": atype, "ok": False, "error": "missing selector"}
        try:
            if atype == "fill":
                await page.fill(selector, text, timeout=action_timeout_ms)
            else:
                await page.type(selector, text, timeout=action_timeout_ms)
            return {"type": atype, "ok": True, "selector": selector}
        except Exception as e:
            return {"type": atype, "ok": False, "selector": selector, "error": _sanitize_error(e)}

    if atype == "press":
        key = action.get("key")
        selector = action.get("selector")
        if not key:
            return {"type": atype, "ok": False, "error": "missing key"}
        try:
            if selector:
                await page.press(selector, key, timeout=action_timeout_ms)
            else:
                await page.keyboard.press(key)
            return {"type": atype, "ok": True, "key": key}
        except Exception as e:
            return {"type": atype, "ok": False, "key": key, "error": _sanitize_error(e)}

    if atype == "evaluate":
        code = action.get("code", "")
        if not code:
            return {"type": atype, "ok": False, "error": "missing code"}
        try:
            result = await page.evaluate(code)
            text = json.dumps(result, ensure_ascii=False, default=str)
            if len(text) > _MAX_BODY_BYTES:
                text = text[:_MAX_BODY_BYTES] + "...[truncated]"
            return {"type": atype, "ok": True, "result": text}
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e)}

    if atype == "screenshot":
        try:
            _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = int(time.time() * 1000)
            path = _SCREENSHOT_DIR / f"shot_{ts}.png"
            await page.screenshot(path=str(path), full_page=action.get("full_page", False))
            result: dict = {"type": atype, "ok": True, "path": str(path)}
            if _MODEL_SUPPORTS_VISION:
                result["_attachments"] = [{"type": "image", "mime": "image/png", "path": str(path)}]
            return result
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e)}

    if atype == "dump_dom":
        try:
            html = await page.content()
            cap = _MAX_BODY_BYTES * 4
            if len(html) > cap:
                html = html[:cap] + "\n...[truncated]"
            return {"type": atype, "ok": True, "html": html}
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e)}

    if atype == "set_cookie":
        cookies = action.get("cookies") or []
        if not cookies:
            return {"type": atype, "ok": False, "error": "missing cookies"}
        try:
            await page.context.add_cookies(cookies)
            return {"type": atype, "ok": True, "count": len(cookies)}
        except Exception as e:
            return {"type": atype, "ok": False, "error": _sanitize_error(e)}

    return {"type": atype, "ok": False, "error": f"unknown action type: {atype}"}


def _sanitize_error(e: Exception) -> str:
    """Turn raw Playwright/Chrome errors into short, actionable messages."""
    msg = str(e)
    lowered = msg.lower()
    if "libnspr4" in lowered or "shared libraries" in lowered or "no such file" in lowered:
        return "missing system deps; run: sudo playwright install-deps chromium"
    if "timeout" in lowered and "exceeded" in lowered:
        return "timeout exceeded"
    if "err_connection_refused" in lowered:
        return "network error: connection refused"
    if "err_name_not_resolved" in lowered:
        return "network error: dns lookup failed"
    if "net::err_" in lowered:
        # Extract the ERR code if possible
        import re
        m = re.search(r"err_([a-z0-9_]+)", lowered)
        if m:
            return f"network error: {m.group(1)}"
        return "network error"
    if "targetclosederror" in lowered:
        return "browser closed unexpectedly"
    return msg[:200]


# ---------------------------------------------------------------------------
# Result builders
# ---------------------------------------------------------------------------


def _build_summary(
    sink_events: list[dict],
    dialogs: list[dict],
    page_errors: list[str],
    console_messages: list[dict],
    network: list[dict],
    actions: list[dict],
) -> dict:
    summary: dict[str, Any] = {
        "sink_hits": len(sink_events),
        "dialog_count": len(dialogs),
        "page_errors": len(page_errors),
        "console_errors": sum(1 for c in console_messages if c.get("type") == "error"),
        "action_failures": sum(1 for a in actions if not a.get("ok")),
    }
    # HTTP status breakdown
    statuses: dict[str, int] = {}
    for entry in network:
        s = entry.get("status")
        if s is not None:
            key = str(s)
            statuses[key] = statuses.get(key, 0) + 1
    if statuses:
        summary["status_breakdown"] = statuses
    # Verdict heuristic
    if sink_events or dialogs:
        summary["verdict"] = "exploit_triggered"
    elif summary["action_failures"]:
        summary["verdict"] = "action_failed"
    elif summary["page_errors"]:
        summary["verdict"] = "page_error"
    else:
        summary["verdict"] = "no_signal"
    return summary


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


async def _browser_execute(
    url: str,
    actions: list[dict] | None = None,
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
    headless: bool = True,
    hook_xss_sinks: bool = True,
    capture_traffic: bool = True,
    capture_bodies: bool = False,
    timeout: int = 90,
    nav_wait_until: str = "load",
    action_timeout_ms: int = _DEFAULT_ACTION_TIMEOUT_MS,
    ignore_https_errors: bool = True,
    viewport: dict | None = None,
) -> str:
    """Run a sequence of browser actions and return captured evidence.

    The first navigation defaults to `url`. Additional actions can navigate,
    interact, evaluate JS, and take screenshots. All HTTP traffic is captured;
    XSS sinks are recorded when hook_xss_sinks=True.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return tool_error(
            "playwright is not installed. Run: uv pip install playwright && playwright install chromium"
        )

    actions = list(actions or [])
    network: list[dict] = []
    network_index: dict = {}
    websocket_frames: list[dict] = []
    console_messages: list[dict] = []
    page_errors: list[str] = []
    dialogs: list[dict] = []
    accumulated_sinks: list[dict] = []
    attachments: list[dict] = []

    started = time.time()

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            try:
                context_kwargs: dict[str, Any] = {
                    "ignore_https_errors": ignore_https_errors,
                }
                if user_agent:
                    context_kwargs["user_agent"] = user_agent
                if headers:
                    context_kwargs["extra_http_headers"] = headers
                if viewport:
                    context_kwargs["viewport"] = viewport

                context = await browser.new_context(**context_kwargs)
                if hook_xss_sinks:
                    await context.add_init_script(_SINK_HOOK_SCRIPT)

                page = await context.new_page()
                page.set_default_timeout(action_timeout_ms)
                page.set_default_navigation_timeout(_DEFAULT_NAV_TIMEOUT_MS)

                # ---- pre-run set_cookie before any nav ----
                for action in actions:
                    if (action.get("type") or "").lower() == "set_cookie":
                        result = await _run_action(page, action, action_timeout_ms)
                        # Merge attachments from set_cookie (none expected, but safe)
                        attachments.extend(result.pop("_attachments", []))

                # ---- traffic capture wiring ----
                if capture_traffic:
                    def on_request(req):
                        try:
                            if capture_bodies:
                                entry = _serialize_request_with_body(req)
                            else:
                                entry = _serialize_request(req)
                            entry["started_at"] = round(time.time() - started, 4)
                            entry["status"] = None
                            entry["response_headers"] = {}
                            if capture_bodies:
                                entry["response_body"] = ""
                            network.append(entry)
                            network_index[req] = entry
                        except Exception:
                            pass

                    async def on_response(resp):
                        try:
                            entry = network_index.get(resp.request)
                            if entry is None:
                                if capture_bodies:
                                    entry = _serialize_request_with_body(resp.request)
                                else:
                                    entry = _serialize_request(resp.request)
                                network.append(entry)
                            entry["status"] = resp.status
                            entry["finished_at"] = round(time.time() - started, 4)
                            try:
                                entry["response_headers"] = dict(resp.headers)
                            except Exception:
                                entry["response_headers"] = {}
                            if capture_bodies:
                                try:
                                    body = await resp.body()
                                    entry["response_body"] = _safe_decode(body)
                                except Exception as e:
                                    entry["response_body"] = f"<unavailable: {e}>"
                        except Exception:
                            pass

                    def on_request_failed(req):
                        try:
                            entry = network_index.get(req)
                            if entry is None:
                                if capture_bodies:
                                    entry = _serialize_request_with_body(req)
                                else:
                                    entry = _serialize_request(req)
                                network.append(entry)
                            entry["failed"] = True
                            entry["failure"] = req.failure or ""
                        except Exception:
                            pass

                    def on_websocket(ws):
                        ws_url = ws.url

                        def on_frame_sent(payload):
                            websocket_frames.append({
                                "url": ws_url, "direction": "sent",
                                "payload": payload[:_MAX_BODY_BYTES] if isinstance(payload, str) else _safe_decode(payload),
                                "ts": round(time.time() - started, 4),
                            })

                        def on_frame_received(payload):
                            websocket_frames.append({
                                "url": ws_url, "direction": "received",
                                "payload": payload[:_MAX_BODY_BYTES] if isinstance(payload, str) else _safe_decode(payload),
                                "ts": round(time.time() - started, 4),
                            })

                        ws.on("framesent", on_frame_sent)
                        ws.on("framereceived", on_frame_received)

                    page.on("request", on_request)
                    page.on("response", on_response)
                    page.on("requestfailed", on_request_failed)
                    page.on("websocket", on_websocket)

                # ---- console / errors / dialogs ----
                def on_console(msg):
                    text = msg.text[:8192]
                    if text.startswith('__ION_SINK__'):
                        try:
                            entry = json.loads(text[len('__ION_SINK__'):])
                            accumulated_sinks.append(entry)
                        except Exception:
                            pass
                        return
                    console_messages.append({
                        "type": msg.type, "text": msg.text[:1024],
                        "ts": round(time.time() - started, 4),
                    })

                page.on("console", on_console)
                page.on("pageerror", lambda err: page_errors.append(str(err)[:1024]))

                async def on_dialog(dialog):
                    dialogs.append({"type": dialog.type, "message": dialog.message[:1024]})
                    try:
                        await dialog.dismiss()
                    except Exception:
                        pass

                page.on("dialog", on_dialog)

                # ---- run primary navigation if no explicit navigate action ----
                results: list[dict] = []
                has_explicit_nav = any((a.get("type") or "").lower() == "navigate" for a in actions)
                if not has_explicit_nav:
                    nav = {"type": "navigate", "url": url, "wait_until": nav_wait_until}
                    results.append(await _run_action(page, nav, _DEFAULT_NAV_TIMEOUT_MS))

                # ---- run user actions with overall timeout budget ----
                deadline = started + timeout
                for action in actions:
                    if (action.get("type") or "").lower() == "set_cookie":
                        continue  # already handled above
                    if time.time() > deadline:
                        results.append({
                            "type": action.get("type"),
                            "ok": False,
                            "error": "overall timeout exceeded",
                        })
                        break
                    result = await _run_action(page, action, action_timeout_ms)
                    attachments.extend(result.pop("_attachments", []))
                    results.append(result)

                # Small settle window for pending async handlers
                await asyncio.sleep(0.2)

                # ---- read any remaining sink events from final page ----
                if hook_xss_sinks:
                    try:
                        final_sinks = await page.evaluate("() => window.__ion_sinks || []") or []
                        accumulated_sinks.extend(final_sinks)
                    except Exception as e:
                        page_errors.append(f"sink read failed: {e}")

                final_url = page.url
                title = ""
                try:
                    title = await page.title()
                except Exception:
                    pass

            finally:
                try:
                    await browser.close()
                except Exception:
                    pass

        # ---- dedupe & cap sinks ----
        sink_events = _dedupe_sinks(accumulated_sinks)
        sink_events = sink_events[:_MAX_SINK_EVENTS]

        summary = _build_summary(
            sink_events=sink_events,
            dialogs=dialogs,
            page_errors=page_errors,
            console_messages=console_messages,
            network=network,
            actions=results,
        )

        truncated_net = network[:_MAX_NETWORK_ENTRIES]

        result_payload = {
            "success": True,
            "summary": summary,
            "final_url": final_url,
            "title": title,
            "actions": results,
            "network": truncated_net,
            "network_total": len(network),
            "websocket_frames": websocket_frames[:_MAX_WEBSOCKET_FRAMES],
            "console": console_messages[:_MAX_CONSOLE_MSGS],
            "page_errors": page_errors[:_MAX_PAGE_ERRORS],
            "dialogs": dialogs,
            "xss_sinks": sink_events,
            "xss_sinks_total": len(accumulated_sinks),
            "elapsed_ms": int((time.time() - started) * 1000),
        }
        if attachments:
            result_payload["_attachments"] = attachments

        return tool_result(result_payload)

    except Exception as e:
        logger.warning(f"browser_execute error: {e}", exc_info=True)
        return tool_error(f"browser_execute failed: {_sanitize_error(e)}")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


BROWSER_EXECUTE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browser_execute",
        "description": (
            "Run a real Chromium browser to verify exploits and inspect SPA/DOM behavior. "
            "Captures every HTTP request and response (including XHR/fetch/WebSocket), "
            "hooks XSS sinks (innerHTML, insertAdjacentHTML, eval, document.write, "
            "setAttribute on event handlers, alert/confirm/prompt, Function constructor, etc.), "
            "records console output, page errors, and JS dialogs. Use this AFTER an HTTP-tool "
            "finding to confirm whether a payload truly executes — not for fast fuzzing. "
            "The first action defaults to navigating to `url`; supply `actions` to interact "
            "with the page (click, type, evaluate JS, screenshot, etc.)."
            "\n\nExample: "
            'actions=[{"type": "fill", "selector": "input[name=q]", "text": "<svg/onload=alert(1)>"}, '
            '{"type": "click", "selector": "button[type=submit]"}, '
            '{"type": "wait_for_load", "state": "networkidle"}]'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Initial URL to navigate to."},
                "actions": {
                    "type": "array",
                    "description": (
                        "Ordered actions executed after the initial navigation. Each action is an object "
                        "with a `type` field. Supported types: "
                        "navigate {url, wait_until?, timeout_ms?}, "
                        "wait {selector, state?}, "
                        "wait_for_load {state?: 'load'|'domcontentloaded'|'networkidle'}, "
                        "wait_ms {ms}, "
                        "click {selector}, "
                        "type {selector, text}, "
                        "fill {selector, text}, "
                        "press {key, selector?}, "
                        "evaluate {code}, "
                        "screenshot {full_page?}, "
                        "dump_dom {}, "
                        "set_cookie {cookies: [{name,value,domain,path,...}]}."
                    ),
                    "items": {"type": "object"},
                },
                "headers": {
                    "type": "object",
                    "description": "Extra HTTP headers applied to every request.",
                    "additionalProperties": {"type": "string"},
                },
                "user_agent": {"type": "string", "description": "Override the User-Agent."},
                "headless": {
                    "type": "boolean",
                    "description": "Run browser headless. Default true.",
                    "default": True,
                },
                "hook_xss_sinks": {
                    "type": "boolean",
                    "description": (
                        "Inject a JS prelude that records writes to dangerous sinks "
                        "(innerHTML, eval, document.write, alert, etc.). Default true."
                    ),
                    "default": True,
                },
                "capture_traffic": {
                    "type": "boolean",
                    "description": "Capture all HTTP/WebSocket traffic metadata. Default true.",
                    "default": True,
                },
                "capture_bodies": {
                    "type": "boolean",
                    "description": (
                        "Capture request/response bodies in the network log. "
                        "Disabled by default to keep output small; enable only when you need to inspect payloads."
                    ),
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Overall timeout for the whole action sequence (seconds). Default 90.",
                    "default": 90,
                },
                "nav_wait_until": {
                    "type": "string",
                    "description": (
                        "wait_until used for the implicit initial navigation. "
                        "Options: 'load' (default), 'domcontentloaded', 'networkidle'."
                    ),
                    "default": "load",
                },
                "action_timeout_ms": {
                    "type": "integer",
                    "description": "Per-action timeout in milliseconds. Default 10000.",
                    "default": _DEFAULT_ACTION_TIMEOUT_MS,
                },
                "ignore_https_errors": {
                    "type": "boolean",
                    "description": "Ignore TLS errors. Default true (test targets often have bad certs).",
                    "default": True,
                },
                "viewport": {
                    "type": "object",
                    "description": "Viewport size, e.g. {width: 1280, height: 800}.",
                    "properties": {
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                },
            },
            "required": ["url"],
        },
    },
}


def _check_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


registry.register(
    name="browser_execute",
    toolset="builtin",
    schema=BROWSER_EXECUTE_SCHEMA,
    handler=_browser_execute,
    check_fn=_check_playwright,
    is_async=True,
    description=(
        "Real Chromium browser execution for verifying exploits. "
        "Captures all requests/responses, hooks XSS sinks, runs JS, takes screenshots."
    ),
    emoji="🌐",
    max_result_size_chars=None,
)
