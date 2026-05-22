import json
import os
import queue
import re
import time
from contextvars import ContextVar
from typing import Any, Optional, Literal

from pydantic import BaseModel
import litellm

from Ion.tools.registry import dispatch
from Ion.subagent_models import (
    Budget,
    StopConditions,
    SubagentLoopTracker,
    SubagentResult,
    SubagentStatus,
    WhyStopped,
    RecommendedOwner,
)


_active_callbacks_ctx: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "_active_callbacks", default=None
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str]


class LoopState(BaseModel):
    messages: list[dict]
    turn_count: int = 0
    finish_reason: Optional[str] = None
    max_turns: int = 0
    context_max_tokens: int = 0
    compression_count: int = 0
    last_prompt_tokens: int = 0
    last_message_count: int = 0
    hook_queue: Optional[Any] = None


# --------------------------------------------------------------------------- #
#  Token estimation & context compression                                     #
# --------------------------------------------------------------------------- #


def _fallback_parse_xml_tool_calls(content: str) -> list[dict]:
    """Parse XML-style tool calls embedded in content (minimax fallback)."""
    if not content or "<invoke" not in content:
        return []

    tool_calls = []
    # Match <invoke name="..."> ... </invoke> (with optional namespace prefix)
    invoke_pattern = r'<(\w+:)?invoke\s+name=["\']([^"\']+)["\']\s*>(.*?)</(\w+:)?invoke>'
    for match in re.finditer(invoke_pattern, content, re.DOTALL):
        name = match.group(2)
        inner = match.group(3)
        args = {}
        # Match <parameter name="...">value</parameter>
        param_pattern = r'<(\w+:)?parameter\s+name=["\']([^"\']+)["\']\s*>(.*?)</(\w+:)?parameter>'
        for pmatch in re.finditer(param_pattern, inner, re.DOTALL):
            param_name = pmatch.group(2)
            param_value = pmatch.group(3).strip()
            args[param_name] = param_value

        if args:
            tool_calls.append(
                {
                    "id": f"xml_fallback_{len(tool_calls):02d}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            )

    return tool_calls


def _char_based_estimate(messages: list[dict]) -> int:
    """Fallback rough token estimator: ~4 chars per token."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content") or ""
        total_chars += len(content)
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total_chars += len(fn.get("name", ""))
            total_chars += len(fn.get("arguments", ""))
    return total_chars // 4


def _estimate_tokens(state: LoopState) -> int:
    """
    Estimate current prompt tokens.

    When actual API usage data is available (from the previous turn),
    use it as the baseline and add an incremental estimate for new
    messages appended since then. Falls back to character-based
    estimation on the first turn.
    """
    if state.last_prompt_tokens <= 0 or state.last_message_count <= 0:
        return _char_based_estimate(state.messages)

    # Estimate delta from messages added since the last API call
    delta_chars = 0
    for msg in state.messages[state.last_message_count :]:
        content = msg.get("content") or ""
        delta_chars += len(content)
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            delta_chars += len(fn.get("name", ""))
            delta_chars += len(fn.get("arguments", ""))
    return state.last_prompt_tokens + (delta_chars // 4)


def _format_history_for_summary(messages: list[dict]) -> str:
    """Convert a slice of messages into plain text for summarization."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content") or ""
        # Multimodal messages may have content as a list of blocks
        if isinstance(content, list):
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = " ".join(texts)
        if role == "assistant" and msg.get("tool_calls"):
            tc_lines = []
            for tc in msg.get("tool_calls", []):
                tc_lines.append(
                    f"  -> Tool call: `{tc.get('function', {}).get('name', '?')}` "
                    f"args={tc.get('function', {}).get('arguments', '{}')}"
                )
            if content:
                lines.append(f"[{role}]\n{content}\n" + "\n".join(tc_lines))
            else:
                lines.append(f"[{role}]\n" + "\n".join(tc_lines))
        elif role == "tool":
            tool_id = msg.get("tool_call_id", "?")
            lines.append(f"[Tool result {tool_id}]\n{content[:1000]}")
        else:
            lines.append(f"[{role}]\n{content}")
    return "\n\n".join(lines)


def _vprint(verbose: bool, *args, **kwargs):
    """Conditional print controlled by verbose flag."""
    if verbose:
        print(*args, **kwargs)


_THINK_RE = re.compile(r"<think\b[^>]*>(.*?)</think>", re.IGNORECASE | re.DOTALL)


def split_display_thinking(
    content: Optional[str], reasoning_content: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """Return display copies of *content* and *reasoning_content*.

    *display_reasoning_content* = *reasoning_content* + all text inside
    ``<think>...</think>`` blocks found in *content*.

    *display_content* = *content* with all ``<think>...</think>`` removed.

    Original fields are never modified.
    """
    if not content:
        return content or None, reasoning_content or None

    think_texts = _THINK_RE.findall(content)
    display_content = _THINK_RE.sub("", content)
    display_content = display_content.strip() or None

    display_reasoning = reasoning_content or ""
    for think_text in think_texts:
        display_reasoning += think_text

    display_reasoning = display_reasoning.strip() or None

    return display_content, display_reasoning


def _compress_context(model_id: str, api_key: str, base_url: str, state: LoopState, logger=None):
    """
    Compress older conversation history by summarizing it via an LLM call.

    Preserves:
      - system prompt + user query (everything up to and including last user msg)
      - the most recent 2 assistant/tool turns
    Everything in between is summarized and injected as a [Context Summary].
    """
    if len(state.messages) <= 3:
        return

    # Locate the last user message (usually index 1, but search to be safe)
    last_user_idx = -1
    for i, msg in enumerate(state.messages):
        if msg.get("role") == "user":
            last_user_idx = i
    if last_user_idx < 0:
        return

    preserved_prefix = state.messages[: last_user_idx + 1]

    # Collect the most recent 2 assistant/tool turns after the user message
    suffix = []
    turn_count = 0
    for msg in reversed(state.messages[last_user_idx + 1 :]):
        suffix.insert(0, msg)
        if msg.get("role") == "assistant":
            turn_count += 1
        if turn_count >= 2:
            break

    to_compress = state.messages[last_user_idx + 1 : len(state.messages) - len(suffix)]
    if not to_compress:
        return

    summary_messages = [
        {
            "role": "system",
            "content": """You have been working on the task described above but have not yet completed it. Write a continuation summary that will allow you (or another instance of yourself) to resume work efficiently in a future context window where the conversation history will be replaced with this summary. Your summary should be structured, concise, and actionable. Include:
1. Task Overview
The user's core request and success criteria
Any clarifications or constraints they specified
2. Current State
What has been completed so far
Files created, modified, or analyzed (with paths if relevant)
Key outputs or artifacts produced
3. Important Discoveries
Technical constraints or requirements uncovered
Decisions made and their rationale
Errors encountered and how they were resolved
What approaches were tried that didn't work (and why)
4. Next Steps
Specific actions needed to complete the task
Any blockers or open questions to resolve
Priority order if multiple steps remain
5. Context to Preserve
User preferences or style requirements
Domain-specific details that aren't obvious
Any promises made to the user
Be concise but complete—err on the side of including information that would prevent duplicate work or repeated mistakes. Write in a way that enables immediate resumption of the task.
Wrap your summary in <summary></summary> tags.""",
        },
        {
            "role": "user",
            "content": _format_history_for_summary(to_compress),
        },
    ]

    try:
        create_kwargs = {
            "model": model_id,
            "messages": list(summary_messages),
            "max_tokens": 4000,
            "stream": False,
        }
        if api_key:
            create_kwargs["api_key"] = api_key
        if base_url:
            create_kwargs["api_base"] = base_url
        summary_resp = litellm.completion(**create_kwargs)
        summary = summary_resp.choices[0].message.content or ""
    except Exception:
        # If summarization fails, fall back to a simple eviction note
        summary = "[Earlier conversation history was evicted due to context limits.]"

    summary_msg = {
        "role": "system",
        "content": f"[Context Summary] Previous turns have been compressed:\n{summary}",
    }

    state.messages = preserved_prefix + [summary_msg] + suffix
    state.compression_count += 1

    if logger and hasattr(logger, "log_compression"):
        logger.log_compression(summary, len(to_compress))


# --------------------------------------------------------------------------- #
#  Core turn / loop logic                                                     #
# --------------------------------------------------------------------------- #


def run_one_turn(
    model_id: str,
    api_key: str,
    base_url: str,
    state: LoopState,
    tools: list[dict],
    logger=None,
    agent_name: str = "root",
    callbacks: Optional[dict[str, Any]] = None,
    verbose: bool = True,
):
    prefix = f"[SubAgent: {agent_name}] " if agent_name != "root" else ""
    prefix_printed = False
    message_id: str | None = None

    _ctx_token = _active_callbacks_ctx.set(callbacks)
    try:
        create_kwargs = {
            "model": model_id,
            "messages": list(state.messages),
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if api_key:
            create_kwargs["api_key"] = api_key
        if base_url:
            create_kwargs["api_base"] = base_url
        response = litellm.completion(**create_kwargs)

        content_parts = []
        reasoning_content_parts = []
        tool_calls_map = {}
        finish_reason = None
        usage = None
        reasoning = False
        reasoning_buffer = ""

        for chunk in response:
            if message_id is None and hasattr(chunk, "id") and chunk.id:
                message_id = chunk.id
                if callbacks:
                    cb = callbacks.get("on_assistant_start")
                    if cb:
                        cb(message_id, agent_name=agent_name)

            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                # usage-only chunk when stream_options is supported
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage
                continue

            delta = choice.delta

            if delta and delta.content:
                if prefix and not prefix_printed:
                    _vprint(verbose, prefix, end="", flush=True)
                    prefix_printed = True
                text = delta.content
                content_parts.append(text)
                if reasoning:
                    reasoning = False
                    _vprint(verbose, "\n</think>\n")
                _vprint(verbose, text, end="", flush=True)
                if callbacks:
                    cb = callbacks.get("on_assistant_chunk")
                    if cb:
                        cb(text, reasoning=False, message_id=message_id, agent_name=agent_name)
            if delta and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc = tool_calls_map[idx]
                    if tc_delta.id:
                        tc["id"] = tc_delta.id
                    if tc_delta.type:
                        tc["type"] = tc_delta.type
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tc["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tc["function"]["arguments"] += tc_delta.function.arguments
            # Try standard reasoning_content (DeepSeek, etc.)
            _reasoning_text = None
            if delta and hasattr(delta, "reasoning_content") and delta.reasoning_content:
                _reasoning_text = delta.reasoning_content
            # Fallback: litellm may put provider-specific fields in model_extra
            if _reasoning_text is None and delta and hasattr(delta, "model_extra") and delta.model_extra:
                _reasoning_text = delta.model_extra.get("reasoning_content")
            if _reasoning_text:
                if prefix and not prefix_printed:
                    _vprint(verbose, prefix, end="", flush=True)
                    prefix_printed = True
                text = _reasoning_text
                reasoning_content_parts.append(text)
                if not reasoning:
                    reasoning = True
                    _vprint(verbose, "<think>\n")
                _vprint(verbose, text, end="", flush=True)
                if callbacks:
                    cb = callbacks.get("on_assistant_chunk")
                    if cb:
                        cb(text, reasoning=True, message_id=message_id, agent_name=agent_name)

            # MiniMax reasoning_split returns cumulative text inside reasoning_details
            _reasoning_details = None
            if delta and hasattr(delta, "reasoning_details") and delta.reasoning_details:
                _reasoning_details = delta.reasoning_details
            if _reasoning_details is None and delta and hasattr(delta, "model_extra") and delta.model_extra:
                _reasoning_details = delta.model_extra.get("reasoning_details")
            if _reasoning_details:
                for detail in _reasoning_details:
                    if isinstance(detail, dict) and "text" in detail:
                        full_text = detail["text"] or ""
                        if len(full_text) > len(reasoning_buffer):
                            text = full_text[len(reasoning_buffer):]
                            reasoning_buffer = full_text
                            if text:
                                if prefix and not prefix_printed:
                                    _vprint(verbose, prefix, end="", flush=True)
                                    prefix_printed = True
                                reasoning_content_parts.append(text)
                                if not reasoning:
                                    reasoning = True
                                    _vprint(verbose, "<think>\n")
                                _vprint(verbose, text, end="", flush=True)
                                if callbacks:
                                    cb = callbacks.get("on_assistant_chunk")
                                    if cb:
                                        cb(text, reasoning=True, message_id=message_id, agent_name=agent_name)

            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

        if reasoning_content_parts:
            _vprint(verbose)
        if content_parts:
            _vprint(verbose)

        reasoning_content = "".join(reasoning_content_parts)
        content = "".join(content_parts)
        tool_calls_data = list(tool_calls_map.values())

        # Fallback: minimax sometimes embeds tool calls as XML in content
        if not tool_calls_data and content:
            fallback_calls = _fallback_parse_xml_tool_calls(content)
            if fallback_calls:
                tool_calls_data = fallback_calls
                finish_reason = "tool_calls"

        if reasoning_content:
            assistant_message = {
                "role": "assistant",
                "content": content or None,
                "reasoning_content": reasoning_content or None,
            }
        else:
            assistant_message = {
                "role": "assistant",
                "content": content or None,
            }
        if tool_calls_data:
            assistant_message["tool_calls"] = tool_calls_data
        state.messages.append(assistant_message)

        if callbacks:
            cb = callbacks.get("on_assistant_end")
            if cb:
                cb(message_id, agent_name=agent_name, tool_calls=tool_calls_data)

        if finish_reason == "tool_calls":
            tool_names = [t["function"]["name"] for t in tool_calls_data]
            exec_prefix = f"[{agent_name}] " if agent_name != "root" else ""
            _vprint(verbose, f"{exec_prefix}🔧 Executing: {', '.join(tool_names)}")
            if callbacks:
                cb = callbacks.get("on_tool_start")
                if cb:
                    cb(tool_names, agent_name=agent_name)

            for tool in tool_calls_data:
                name = tool["function"]["name"]
                try:
                    args = json.loads(tool["function"]["arguments"])
                except json.JSONDecodeError as e:
                    # retry 3
                    _vprint(verbose, f"[ERROR]:{e}")
                    continue
                except Exception as e:
                    _vprint(verbose, f"[ERROR]:{e}")
                    continue
                start = time.time()

                output = dispatch(name, **args)
                duration = (time.time() - start) * 1000

                # Strip _attachments from output so it doesn't bloat tool result text
                image_attachments: list[dict] = []
                try:
                    parsed_output = json.loads(output)
                    if isinstance(parsed_output, dict) and "_attachments" in parsed_output:
                        image_attachments = parsed_output.pop("_attachments")
                        output = json.dumps(parsed_output, ensure_ascii=False)
                except Exception:
                    pass

                if logger:
                    logger.log_tool_call(name, args, output, duration)
                if callbacks:
                    cb = callbacks.get("on_tool_result")
                    if cb:
                        cb(name, output, duration, agent_name=agent_name, arguments=args, tool_call_id=tool["id"])

                state.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool["id"],
                        "content": output,
                    }
                )

                # If model supports vision, inject screenshot as a follow-up user message
                if image_attachments and os.getenv("MODEL_SUPPORTS_VISION", "").lower() in (
                    "1",
                    "true",
                    "yes",
                ):
                    try:
                        import base64

                        content_blocks: list[dict] = []
                        for att in image_attachments:
                            if att.get("type") == "image":
                                img_path = att.get("path")
                                if img_path and os.path.exists(img_path):
                                    with open(img_path, "rb") as f:
                                        b64 = base64.b64encode(f.read()).decode()
                                    content_blocks.append(
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:{att.get('mime', 'image/png')};base64,{b64}"
                                            },
                                        }
                                    )
                        if content_blocks:
                            state.messages.append(
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": f"[{name} screenshot]"},
                                        *content_blocks,
                                    ],
                                }
                            )
                    except Exception:
                        pass

        state.turn_count += 1
        state.finish_reason = finish_reason

        if usage:
            if logger:
                logger.record_token_usage(usage.model_dump())
            state.last_prompt_tokens = usage.prompt_tokens
            state.last_message_count = len(state.messages)
        elif logger and hasattr(response, "usage") and response.usage:
            logger.record_token_usage(response.usage.model_dump())
            state.last_prompt_tokens = response.usage.prompt_tokens
            state.last_message_count = len(state.messages)
    finally:
        _active_callbacks_ctx.reset(_ctx_token)


def _check_and_inject_hooks(state: LoopState):
    """Drain any pending user hook messages into the conversation."""
    if state.hook_queue is None:
        return
    hooks = []
    while True:
        try:
            hooks.append(state.hook_queue.get_nowait())
        except queue.Empty:
            break
    for hook_content in hooks:
        state.messages.append({"role": "user", "content": hook_content})


def run_agent_loop(
    model_id: str,
    api_key: str,
    base_url: str,
    state: LoopState,
    tools: list[dict],
    logger=None,
    on_before_turn=None,
    agent_name: str = "root",
    callbacks: Optional[dict[str, Any]] = None,
    pause_check: Optional[callable] = None,
    verbose: bool = True,
):
    """
    Run the agent loop until a non-tool-calls finish reason is reached.

    Args:
        on_before_turn: Optional callback(state) invoked before each turn.
                        Can be used by specialized loops for pre-turn hooks.
        agent_name: Identifier used for stdout prefixing (sub-agents).
        callbacks: Optional dict of callbacks for streaming events.
                   Supported keys: on_assistant_chunk, on_tool_start,
                   on_tool_result, on_turn_complete.
        verbose: If True (default), print streaming output to stdout.
                 Set to False to suppress stdout (e.g., web mode).
    """
    from Ion.observability import _observability_logger_ctx

    token = None
    if logger is not None:
        token = _observability_logger_ctx.set(logger)
    try:
        while True:
            # --- max turns guard ---
            if state.max_turns > 0 and state.turn_count >= state.max_turns:
                state.finish_reason = "max_turns_reached"
                return

            # --- pre-turn context compression ---
            if state.context_max_tokens > 0:
                estimated = _estimate_tokens(state)
                if estimated > state.context_max_tokens - 20000:
                    _compress_context(model_id, api_key, base_url, state, logger)

            if on_before_turn is not None:
                on_before_turn(state)

            _check_and_inject_hooks(state)

            run_one_turn(model_id, api_key, base_url, state, tools, logger, agent_name=agent_name, callbacks=callbacks, verbose=verbose)

            if callbacks:
                cb = callbacks.get("on_turn_complete")
                if cb:
                    cb(state.turn_count, state.finish_reason)

            # --- pause check ---
            if pause_check is not None:
                pause_check()

            # --- post-turn length handling ---
            if state.finish_reason == "length":
                # Remove the truncated assistant message before compressing
                if state.messages and state.messages[-1].get("role") == "assistant":
                    state.messages.pop()
                _compress_context(model_id, api_key, base_url, state, logger)
                state.finish_reason = None
                continue  # retry the turn after compression

            if state.finish_reason != "tool_calls":
                return
    finally:
        if token is not None:
            _observability_logger_ctx.reset(token)


# --------------------------------------------------------------------------- #
#  Sub-agent loop with budget controls                                        #
# --------------------------------------------------------------------------- #


def _build_termination_message(reason: str, tracker: SubagentLoopTracker) -> str:
    """Build a forced-termination message that guides the model to emit JSON."""
    return (
        f"\n[SYSTEM] Forced termination: {reason}.\n"
        f"Turns used: {tracker.tool_call_count} tool calls.\n"
        "You must now output your final structured result as a single JSON object "
        "matching the required schema. Do not add extra commentary outside the JSON."
    )


def _has_progress(state: LoopState, tracker: SubagentLoopTracker) -> bool:
    """Heuristic: did the last turn produce new information?"""
    if len(state.messages) < 2:
        return True

    last_msg = state.messages[-1]
    role = last_msg.get("role", "")

    # If the last message is a tool result, deeply analyze for progress
    if role == "tool":
        content = last_msg.get("content", "")
        if not content or len(content) < 5:
            tracker.record_attempt_result("no_signal")
            return False

        content_lower = content.lower()

        # Check for error patterns
        is_error = content.startswith('{"error"') or "error" in content[:100].lower()
        if is_error:
            tracker.record_error(content)
            tracker.record_attempt_result("failed")
            # An error is information if it's different from previous errors
            return tracker.consecutive_same_error_count <= 1

        # Check for signals of genuine progress
        progress_signals = [
            # New data discovered
            "flag{" in content_lower,
            "flag is" in content_lower,
            "password" in content_lower,
            "secret" in content_lower,
            # HTTP response variations that indicate different behavior
            '"status": 200' in content or '"status": 500' in content,
            '"status": 403' in content or '"status": 401' in content,
            # IDOR / enumeration: content-length differences signal unauthorized data access
            "content-length" in content_lower
            and (
                "different" in content_lower
                or "anomal" in content_lower
                or "outlier" in content_lower
            ),
            "length=" in content_lower
            and (
                "diff" in content_lower
                or "vary" in content_lower
                or "cluster" in content_lower
            ),
            "status: 200" in content_lower
            and "len=" in content_lower,  # enumeration output listing HTTP responses
            # File content / source code
            "<?php" in content_lower,
            "import " in content_lower,
            "config" in content_lower,
            # Database / SQL indicators
            "mysql" in content_lower,
            "sqlite" in content_lower,
            "table" in content_lower,
            "column" in content_lower,
            # Successful exploitation signs
            "root@" in content_lower,
            "uid=" in content_lower,
        ]

        if any(progress_signals):
            tracker.record_attempt_result("success")
            return True

        # Check if content is substantially different from previous tool results
        content_sig = content[:300]
        recent_sigs = []
        for msg in state.messages[:-1]:
            if msg.get("role") == "tool":
                recent_sigs.append(msg.get("content", "")[:300])
        if recent_sigs and content_sig not in recent_sigs:
            tracker.record_attempt_result("success")
            return True

        tracker.record_attempt_result("no_signal")
        return False

    # If assistant produced content (not just tool calls), check for novelty
    if role == "assistant":
        content = last_msg.get("content") or ""
        if not content:
            return False
        # Very short or repetitive summaries indicate no progress
        if len(content) < 30:
            return False
        # Check if assistant is reporting findings or just planning
        finding_keywords = [
            "found",
            "discovered",
            "confirmed",
            "identified",
            "extracted",
            "successful",
            "different length",
            "content-length",
            "anomaly",
            "outlier",
            "unauthorized",
        ]
        if any(kw in content.lower() for kw in finding_keywords):
            return True
        return True

    return True


def _map_violation_to_why(violation: str) -> WhyStopped:
    """Map budget violation string to WhyStopped enum."""
    if violation == "tool_limit":
        return WhyStopped.TOOL_LIMIT
    if violation == "no_progress":
        return WhyStopped.NO_PROGRESS
    if violation == "duplicate_tool_call":
        return WhyStopped.BLOCKED
    if violation == "same_error_limit":
        return WhyStopped.SAME_ERROR_LIMIT
    if violation.startswith("low_success_rate"):
        return WhyStopped.LOW_SUCCESS_RATE
    if violation.startswith("blocked_keyword"):
        return WhyStopped.STOP_CONDITION
    if violation == "stop_condition_same_error":
        return WhyStopped.STOP_CONDITION
    return WhyStopped.BUDGET_EXHAUSTED


def run_subagent_loop(
    model_id: str,
    api_key: str,
    base_url: str,
    state: LoopState,
    tools: list[dict],
    budget: Budget,
    logger=None,
    on_before_turn=None,
    agent_name: str = "subagent",
    stop_conditions: Optional[Any] = None,
    callbacks: Optional[dict[str, Any]] = None,
    verbose: bool = True,
    goal: str = "",
) -> SubagentResult:
    """
    Run a controlled sub-agent loop with budget enforcement and anti-loop guards.

    Returns a structured SubagentResult regardless of how the loop exits.
    """
    from Ion.observability import _observability_logger_ctx

    tracker = SubagentLoopTracker()
    tracker.status_transitions.append("started")

    token = None
    if logger is not None:
        token = _observability_logger_ctx.set(logger)

    try:
        while True:
            # --- max turns guard ---
            if budget.max_turns > 0 and state.turn_count >= budget.max_turns:
                state.finish_reason = "max_turns_reached"
                tracker.status_transitions.append("max_turns_reached")
                _inject_termination_message(state, "max_turns_reached")
                _force_final_turn(
                    model_id, api_key, base_url, state, tools, logger, agent_name,
                    callbacks=callbacks, verbose=verbose,
                )
                return _extract_result(state, tracker, WhyStopped.MAX_TURNS, goal=goal)

            # --- pre-turn context compression ---
            if state.context_max_tokens > 0:
                estimated = _estimate_tokens(state)
                if estimated > state.context_max_tokens - 20000:
                    _compress_context(model_id, api_key, base_url, state, logger)

            if on_before_turn is not None:
                on_before_turn(state)

            run_one_turn(
                model_id, api_key, base_url, state, tools, logger,
                agent_name=agent_name, callbacks=callbacks, verbose=verbose,
            )

            # --- track tool calls from the assistant message just produced ---
            if state.messages:
                last_msg = state.messages[-1]
                if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
                    for tc in last_msg["tool_calls"]:
                        fn = tc.get("function", {})
                        tname = fn.get("name", "")
                        targs = fn.get("arguments", "{}")
                        try:
                            args = (
                                json.loads(targs) if isinstance(targs, str) else targs
                            )
                        except Exception:
                            args = {}
                        tracker.record_tool_call(tname, args)

            # --- progress tracking ---
            has_progress = _has_progress(state, tracker)
            tracker.mark_progress(has_progress)

            # --- budget checks (post-turn) ---
            latest_content = ""
            if state.messages:
                raw_content = state.messages[-1].get("content", "") or ""
                if isinstance(raw_content, list):
                    texts = [
                        part.get("text", "")
                        for part in raw_content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    latest_content = " ".join(texts)
                else:
                    latest_content = raw_content
            budget_violation = tracker.check_budget(
                budget, latest_content=latest_content, stop_conditions=stop_conditions
            )
            if budget_violation:
                tracker.status_transitions.append(f"budget:{budget_violation}")
                _inject_termination_message(state, budget_violation)
                _force_final_turn(
                    model_id, api_key, base_url, state, tools, logger, agent_name,
                    callbacks=callbacks, verbose=verbose,
                )
                why = _map_violation_to_why(budget_violation)
                return _extract_result(state, tracker, why, goal=goal)

            # --- post-turn length handling ---
            if state.finish_reason == "length":
                if state.messages and state.messages[-1].get("role") == "assistant":
                    state.messages.pop()
                _compress_context(model_id, api_key, base_url, state, logger)
                state.finish_reason = None
                continue

            if state.finish_reason != "tool_calls":
                # Natural stop (stop, etc.) — but if the model gave free-text
                # instead of the required JSON object, force one more JSON-only
                # turn so the parent gets structured findings rather than a
                # narrative half-thought.
                tracker.status_transitions.append(f"natural:{state.finish_reason}")
                last_text = _latest_assistant_content(state)
                if not _looks_like_task_summary(last_text):
                    _inject_termination_message(
                        state, f"natural_stop_without_json:{state.finish_reason}"
                    )
                    _force_final_turn(
                        model_id, api_key, base_url, state, tools, logger, agent_name,
                        callbacks=callbacks, verbose=verbose,
                    )
                return _extract_result(state, tracker, WhyStopped.SUCCESS, goal=goal)

    except Exception as exc:
        tracker.status_transitions.append(f"error:{exc}")
        return SubagentResult(
            status=SubagentStatus.FAILED,
            summary=f"Subagent loop crashed: {exc}",
            why_stopped=WhyStopped.BLOCKED,
            recommended_owner=RecommendedOwner.PARENT,
        )
    finally:
        if token is not None:
            _observability_logger_ctx.reset(token)


def _inject_termination_message(state: LoopState, reason: str):
    """Append a system message forcing the model to terminate with a Task Summary."""
    msg = (
        f"\n[SYSTEM] Execution halted: {reason}.\n"
        "You must now output your final Task Summary.\n\n"
        "Write 2-6 sentences in natural language covering:\n"
        "1. What was the subtask goal (restate it).\n"
        "2. What tools or approaches did you try?\n"
        "3. What did you find? Name concrete values: IPs, ports, status codes, file paths, errors.\n"
        "4. If blocked or failed — WHY?\n\n"
        "Rules:\n"
        "- Write in past tense, as a report, NOT a plan.\n"
        "- NEVER start with planning verbs (首先, 接下来, Let's, I will, Plan:, Step 1).\n"
        "- NEVER end with ':', '：', '?', or '...'.\n"
        "- After the summary, you MAY append a small JSON block with ONLY these fields:\n"
        '  {"status": "...", "goal_recap": "...", "confidence": "...", "success_criteria_met": true|false, "why_stopped": "...", "recommended_next_action": "...", "recommended_owner": "parent|same_agent|other_agent"}\n'
        "- Do NOT put summary, key_findings, evidence, attempted_actions, or artifacts inside the JSON.\n"
        "- If you are unsure about the JSON, skip it. The summary alone is sufficient."
    )
    state.messages.append({"role": "system", "content": msg})


def _force_final_turn(
    model_id: str,
    api_key: str,
    base_url: str,
    state: LoopState,
    tools: list[dict],
    logger,
    agent_name: str,
    callbacks: Optional[dict[str, Any]] = None,
    verbose: bool = True,
):
    """Run one final turn after forced termination to collect JSON output."""
    try:
        # Temporarily remove tools so the model can only output text
        run_one_turn(
            model_id, api_key, base_url, state, [], logger,
            agent_name=agent_name, callbacks=callbacks, verbose=verbose,
        )
    except Exception:
        pass


def _summary_looks_unusable(text: str) -> bool:
    """Detect summaries that are planning fragments rather than conclusions.

    The parent agent only sees the JSON, so a useless ``summary`` field
    silently degrades the whole delegation. This catches the most common
    failure modes from small models:
      - Too short to carry any conclusion.
      - Ends with ``:``/``：``/``?``/``？``/``...`` (mid-thought).
      - Starts with planning verbs and lacks concrete observations.
    """
    if not text:
        return True
    s = text.strip()
    if not s:
        return True
    # Strip trailing punctuation/whitespace for the suffix check
    suffix_marker = s.rstrip()
    if suffix_marker.endswith((":", "：", "?", "？", "...", "…")):
        return True
    # Too terse to be a real conclusion
    if len(s) < 20:
        return True
    # Planning starters: only flag when the sentence is short, because longer
    # text often does include a conclusion after the planning verb.
    planning_starters = (
        "首先", "接下来", "下面", "我将", "我会", "让我", "计划",
        "now i", "now let", "let's", "i'll", "i will", "i'm going",
        "plan:", "step 1", "step1", "first,", "first ",
    )
    s_lower = s.lower()
    if len(s) < 120 and any(s_lower.startswith(p) for p in planning_starters):
        return True
    return False


def _build_fallback_summary(
    goal: str,
    success_criteria_met: bool,
    why_stopped: WhyStopped,
    key_findings: list[str],
    attempted_actions: list,
) -> str:
    """Build a goal-aware summary when the subagent failed to produce one.

    Surfaces what the parent actually needs:
      - The goal (so the parent knows what was attempted).
      - The verdict from ``why_stopped`` / ``success_criteria_met``.
      - The top-most synthesized findings (already content-bearing thanks
        to ``_pick_finding_snippet``).
    """
    goal_short = (goal or "").strip()
    if len(goal_short) > 160:
        goal_short = goal_short[:159] + "…"

    if success_criteria_met:
        verdict = "success criteria met"
    elif why_stopped in (
        WhyStopped.BLOCKED,
        WhyStopped.NO_PROGRESS,
        WhyStopped.SAME_ERROR_LIMIT,
        WhyStopped.LOW_SUCCESS_RATE,
        WhyStopped.STOP_CONDITION,
        WhyStopped.WRONG_CAPABILITY,
    ):
        verdict = f"stopped ({why_stopped.value})"
    elif why_stopped in (
        WhyStopped.BUDGET_EXHAUSTED,
        WhyStopped.TOOL_LIMIT,
        WhyStopped.MAX_TURNS,
    ):
        verdict = f"budget exhausted ({why_stopped.value})"
    else:
        verdict = "no structured conclusion produced"

    n_actions = len(attempted_actions or [])
    findings_preview = ""
    if key_findings:
        head = key_findings[:2]
        findings_preview = " | ".join(
            f if len(f) <= 200 else f[:199] + "…" for f in head
        )

    # Distinguish "model produced JSON but a garbage summary" from
    # "model didn't produce JSON at all" so the parent knows whether
    # to trust the rest of the fields (goal_recap, status, etc.).
    if key_findings and verdict == "no structured conclusion produced":
        verdict = "subagent wrote structured JSON but an unusable summary"

    parts = [
        f"[auto-synthesized] goal: {goal_short or '(unspecified)'}",
        f"verdict: {verdict}",
        f"actions: {n_actions}",
    ]
    if findings_preview:
        parts.append(f"top findings: {findings_preview}")
    parts.append("see key_findings/attempted_actions for full content.")
    return "; ".join(parts)


def _extract_result(
    state: LoopState,
    tracker: SubagentLoopTracker,
    why: WhyStopped,
    goal: str = "",
) -> SubagentResult:
    """Extract a SubagentResult from the loop state's final messages."""
    raw_output = ""
    if state.messages:
        # Search backwards for assistant content
        for msg in reversed(state.messages):
            if msg.get("role") == "assistant":
                content = msg.get("content") or ""
                if content:
                    raw_output = content
                    break

    if not raw_output:
        raw_output = "No output produced."

    # Try structured parse first
    result = SubagentResult.from_raw_output(raw_output)
    result.why_stopped = why

    # If status not already set by model, infer from why_stopped
    if result.status == SubagentStatus.FAILED and why == WhyStopped.SUCCESS:
        result.status = SubagentStatus.COMPLETED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.MAX_TURNS:
        result.status = SubagentStatus.BUDGET_EXHAUSTED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.TOOL_LIMIT:
        result.status = SubagentStatus.BUDGET_EXHAUSTED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.NO_PROGRESS:
        result.status = SubagentStatus.BLOCKED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.SAME_ERROR_LIMIT:
        result.status = SubagentStatus.BLOCKED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.LOW_SUCCESS_RATE:
        result.status = SubagentStatus.BLOCKED
    elif result.status == SubagentStatus.FAILED and why == WhyStopped.STOP_CONDITION:
        result.status = SubagentStatus.BLOCKED

    # Auto-enrich empty list fields from tool calls + tool results in messages.
    # The model is expected to populate these, but K-class small models often
    # leave them empty. Without this fallback the parent agent has no idea
    # which tools were run and ends up re-doing the work.
    synth = _synthesize_from_messages(state.messages)
    if not result.attempted_actions and synth["attempted_actions"]:
        result.attempted_actions = synth["attempted_actions"]
    if not result.evidence and synth["evidence"]:
        result.evidence = synth["evidence"]
    if not result.artifacts and synth["artifacts"]:
        result.artifacts = synth["artifacts"]
    if not result.key_findings and synth["key_findings"]:
        result.key_findings = synth["key_findings"]

    # --- Quality gate on the report text the parent actually reads ---
    # goal_recap: if empty, anchor it on the goal we were given.
    if not (result.goal_recap or "").strip() and goal:
        recap = goal.strip()
        if len(recap) > 200:
            recap = recap[:199] + "…"
        result.goal_recap = recap

    # summary: replace narrative fragments / planning preambles with a
    # goal-aware synthesized line so the parent gets actionable signal.
    if _summary_looks_unusable(result.summary):
        result.summary = _build_fallback_summary(
            goal=goal,
            success_criteria_met=result.success_criteria_met,
            why_stopped=why,
            key_findings=result.key_findings,
            attempted_actions=result.attempted_actions,
        )

    # If still failed but we have key findings, mark as partial
    if result.status == SubagentStatus.FAILED and result.key_findings:
        result.status = SubagentStatus.PARTIAL

    return result


def _latest_assistant_content(state: LoopState) -> str:
    """Return text content of the most recent assistant message, or empty string."""
    for msg in reversed(state.messages):
        if msg.get("role") == "assistant":
            content = msg.get("content") or ""
            if isinstance(content, list):
                texts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                content = " ".join(texts)
            if content:
                return content
    return ""


def _looks_like_task_summary(text: str) -> bool:
    """Best-effort check that the text is a substantive task summary.

    With the natural-language-first contract the model may output:
      - A few sentences of findings (GOOD)
      - A short planning fragment like "首先进行...:" (BAD)
      - A bare JSON object with metadata only (ACCEPTABLE — _extract_result will merge it)

    We return True when the text is long enough and does NOT look like an
    unfinished planning preamble.
    """
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    # Very short → probably not a real summary yet.
    if len(s) < 40:
        return False
    # Planning starters that end mid-sentence are a red flag.
    planning_starters = (
        "首先", "接下来", "下面", "然后", "我将", "我会", "让我", "计划",
        "now i", "now let", "let's", "i'll", "i will", "i'm going",
        "plan:", "step 1", "step1", "first,", "first ",
    )
    s_lower = s.lower()
    if len(s) < 120 and any(s_lower.startswith(p) for p in planning_starters):
        return False
    # If it ends with a colon/question mark it's mid-thought.
    if s.rstrip().endswith((":", "：", "?", "？", "...", "…")):
        return False
    # A bare JSON object (with no natural language) is not a task summary.
    stripped = s.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            json.loads(stripped)
            return False
        except Exception:
            pass
    return True


def _extract_paths_from_command(cmd: str) -> list[str]:
    """Pull output-file paths out of a shell command string.

    Catches the common nmap/curl/etc. patterns:
      ``-o /path``, ``-oA /path``, ``-oN /path``, ``-oG /path`` (nmap variants)
      ``--output /path``, ``--output=/path``, ``-o=/path``
      ``> /path``, ``>> /path`` (stdout/stderr redirects)
      ``tee /path``, ``tee -a /path``

    Only returns paths that look like absolute or workspace-rooted files.
    """
    if not cmd or not isinstance(cmd, str):
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        p = p.strip().strip('"').strip("'")
        if not p or p in seen:
            return
        # Filter to anything that plausibly references a path
        if not (p.startswith("/") or p.startswith("./") or p.startswith("~")):
            return
        seen.add(p)
        out.append(p)

    # nmap-style flags (-o, -oA, -oN, -oG, -oX, -oS), curl/wget --output, etc.
    for m in re.finditer(
        r"(?:^|\s)-o[ANGXS]?(?:=|\s+)(\S+)",
        cmd,
    ):
        _add(m.group(1))
    for m in re.finditer(r"--output(?:=|\s+)(\S+)", cmd):
        _add(m.group(1))
    # Output redirects
    for m in re.finditer(r"(?:^|\s)>{1,2}\s*(\S+)", cmd):
        _add(m.group(1))
    # tee / tee -a
    for m in re.finditer(r"\btee\s+(?:-a\s+)?(\S+)", cmd):
        _add(m.group(1))

    return out


def _action_tag(tool_name: str, args_obj: dict | str | None) -> str:
    """Pick a per-call tag for ``key_findings``. For shell-style wrappers,
    prefer the actual program being run (``nmap``, ``curl``, ...) over the
    wrapper name (``bash``) so the parent can tell calls apart."""
    name = (tool_name or "").lower()
    shell_names = ("bash", "sh", "shell", "exec", "run_shell", "execute")
    if name not in shell_names or not isinstance(args_obj, dict):
        return tool_name or "tool"

    # Tokens that prefix the *real* command without being it.
    skip_prefixes = {"sudo", "time", "nice", "ionice", "stdbuf", "exec", "env"}

    for key in ("command", "cmd", "script", "code", "shell"):
        v = args_obj.get(key)
        if not isinstance(v, str) or not v.strip():
            continue
        tokens = v.strip().split()
        for tok in tokens:
            # Skip env-var assignments (FOO=bar) and known prefix words.
            if "=" in tok and not tok.startswith("/") and not tok.startswith("-"):
                continue
            if tok in skip_prefixes:
                continue
            # Drop a leading directory like `/usr/bin/nmap`
            if "/" in tok:
                tok = tok.rsplit("/", 1)[-1]
            if tok and tok.replace("_", "").replace("-", "").replace(".", "").isalnum():
                return f"{tool_name}:{tok}"
            return tool_name
        return tool_name
    return tool_name


def _pick_finding_snippet(raw: str, max_lines: int = 3, line_limit: int = 140) -> str:
    """Pick a short, content-bearing preview from a tool result.

    The goal is to give the parent agent enough signal to act without having
    to re-run the tool, while staying compact. We:
      - Drop empty lines and lines that are pure decoration (`===`, `---`).
      - Drop lines that match obvious tool boot/footer noise (e.g., nmap's
        "Starting Nmap ..." or "Nmap done").
      - Skip label-only lines like ``Response Headers:`` (colon at end with
        no content after it) because the actual data lives on the next line(s).
      - For http_request-style output, prefer body content over header labels.
      - Keep at most `max_lines` lines, each trimmed to `line_limit` chars.
    """
    if not raw or not isinstance(raw, str):
        return ""

    # Try JSON envelope first ({"output": "..."} / {"error": "..."}) so we
    # quote the payload, not the wrapper.
    body = raw.strip()
    if body.startswith("{") and body.endswith("}"):
        try:
            obj = json.loads(body)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            for key in ("output", "stdout", "result", "error", "message", "data"):
                v = obj.get(key)
                if isinstance(v, str) and v.strip():
                    body = v
                    break

    lines = body.splitlines()

    # Detect http_request format (starts with Status: / Final URL:).
    # For these, the interesting content is usually after the last
    # double-blank-line separator (body), not in the header labels.
    is_http_output = False
    if len(lines) >= 2:
        is_http_output = (
            lines[0].strip().startswith("Status:")
            and any(l.strip().startswith("Final URL:") for l in lines[:5])
        )

    noise_patterns = (
        r"^starting nmap",
        r"^nmap done:",
        r"^scanning .* \[",
        r"^pre-scan script",
        r"^[*=\-_]{3,}$",
    )
    noise_re = re.compile("|".join(noise_patterns), re.IGNORECASE)

    def _is_label_only(text: str, next_line: str | None) -> bool:
        """A line like ``Response Headers:`` is a label; the data follows."""
        if not text.rstrip().endswith(":"):
            return False
        # If the next line is indented (continuation) or also short label,
        # skip this one because the real info is on subsequent lines.
        if next_line is not None:
            nxt = next_line.strip()
            if nxt and not nxt.endswith(":"):
                # The next line has actual data → current line is a label.
                return True
        return False

    # Build candidate list with optional http-aware reordering.
    candidates: list[str] = []
    if is_http_output:
        # Phase 1: grab Status + Final URL (they anchor the finding).
        for line in lines:
            s = line.strip()
            if s.startswith("Status:") or s.startswith("Final URL:"):
                candidates.append(s)
        # Phase 2: grab lines from the BODY (after the last blank line).
        last_blank = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "":
                last_blank = i
                break
        if last_blank >= 0:
            for line in lines[last_blank + 1 :]:
                s = line.strip()
                if s:
                    candidates.append(s)
    else:
        for line in lines:
            s = line.strip()
            if s:
                candidates.append(s)

    picked: list[str] = []
    for idx, s in enumerate(candidates):
        if not s:
            continue
        if noise_re.search(s):
            continue
        # Skip label-only lines (e.g., "Response Headers:", "Cookies:")
        nxt = candidates[idx + 1] if idx + 1 < len(candidates) else None
        if _is_label_only(s, nxt):
            continue
        # ANSI escape stripping (best-effort, common shell output)
        s = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", s).strip()
        if not s:
            continue
        if len(s) > line_limit:
            s = s[: line_limit - 1] + "…"
        picked.append(s)
        if len(picked) >= max_lines:
            break

    if not picked:
        # Fallback: take the first non-empty stripped line, even if it looked noisy.
        for line in lines:
            s = line.strip()
            if s:
                if len(s) > line_limit:
                    s = s[: line_limit - 1] + "…"
                picked.append(s)
                break

    return " | ".join(picked)


def _synthesize_from_messages(messages: list[dict]) -> dict[str, list]:
    """Build a compact safety-net summary from tool calls when the subagent
    forgot to populate the structured fields.

    Design intent: the whole point of delegating to a subagent is to compress
    context for the parent. Re-injecting raw tool output into ``evidence``
    would defeat that. So this helper is deliberately stingy:

    - ``attempted_actions``: compact "tool(arg=val) -> success|failed" entries.
      Lets the parent know what was tried so it does not redo the same work.
    - ``artifacts``: file paths only (declared as arguments, or output redirects
      embedded inside shell commands). The parent can read them on demand.
    - ``key_findings``: ONE per-tool summary line ("nmap returned 320 chars,
      classified success") — a header note, not a content dump.
    - ``evidence``: intentionally NOT auto-populated. Curating evidence is
      the model's job; if it skipped, the parent gets the action list and
      artifact paths and decides whether to dig deeper.
    """
    from Ion.subagent_models import AttemptedAction, Artifact

    ordered_calls: list[tuple[str, str, str]] = []  # (id, name, args_json)

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            tc_id = tc.get("id", "")
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "") or ""
            args = fn.get("arguments", "") or ""
            if isinstance(args, dict):
                try:
                    args = json.dumps(args, ensure_ascii=False)
                except Exception:
                    args = str(args)
            ordered_calls.append((tc_id, name, args))

    # Map tool_call_id -> tool result content (kept around only for length /
    # classification — never copied into evidence).
    result_map: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        tc_id = msg.get("tool_call_id", "")
        content = msg.get("content", "") or ""
        if isinstance(content, list):
            texts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            content = " ".join(texts)
        result_map[tc_id] = str(content)

    attempted: list[AttemptedAction] = []
    artifacts: list[Artifact] = []
    key_findings: list[str] = []
    seen_artifact_paths: set[str] = set()

    # Args that *are* the action (don't truncate them aggressively).
    _COMMAND_KEYS = ("command", "cmd", "script", "code", "shell")

    for tc_id, name, args in ordered_calls:
        raw_result = result_map.get(tc_id, "")
        result_kind = _classify_tool_result(raw_result)

        try:
            args_obj = json.loads(args) if args else {}
        except Exception:
            args_obj = {}

        # Build action preview. For command-style args, the command IS the
        # action — give it ~200 chars instead of the default 60.
        if isinstance(args_obj, dict):
            preview_parts = []
            for k, v in list(args_obj.items())[:4]:
                limit = 200 if k.lower() in _COMMAND_KEYS else 60
                preview_parts.append(f"{k}={_short(str(v), limit)}")
            arg_preview = ", ".join(preview_parts)
        else:
            arg_preview = _short(str(args), 200)
        action_text = f"{name}({arg_preview})" if arg_preview else name

        why_text = ""
        if result_kind == "failed":
            why_text = _short(_first_error_line(raw_result), 200)
        elif result_kind == "no_signal":
            why_text = "empty or non-actionable response"

        attempted.append(
            AttemptedAction(action=action_text, result=result_kind, why=why_text)
        )

        # Artifacts pass 1: explicit file/output path arguments.
        if isinstance(args_obj, dict):
            for k, v in args_obj.items():
                if not isinstance(v, str) or not v:
                    continue
                kl = k.lower()
                if any(t in kl for t in ("path", "file", "output", "out_dir")):
                    if v in seen_artifact_paths:
                        continue
                    seen_artifact_paths.add(v)
                    artifacts.append(
                        Artifact(path=v, description=f"argument to {name}")
                    )

        # Artifacts pass 2: paths embedded inside shell command strings
        # (`-oA /tmp/x`, `--output=/tmp/y`, `> /tmp/z`, `tee /tmp/w`, etc.).
        if isinstance(args_obj, dict):
            for k, v in args_obj.items():
                if k.lower() not in _COMMAND_KEYS or not isinstance(v, str):
                    continue
                for path in _extract_paths_from_command(v):
                    if path in seen_artifact_paths:
                        continue
                    seen_artifact_paths.add(path)
                    artifacts.append(
                        Artifact(path=path, description=f"output of {name}")
                    )

            # Per-tool header note + a short content snippet so the parent agent
        # gets actionable signal, not just "tool X ran". For shell-style
        # tools, prefer the actual program name (`nmap`, `curl`, ...) over
        # the wrapper name so multiple bash calls are distinguishable.
        if raw_result and name not in ("update_task", "create_task"):
            tag = _action_tag(name, args_obj)
            snippet = _pick_finding_snippet(raw_result)
            if snippet:
                line = f"[{tag}] {result_kind} ({len(raw_result)} chars): {snippet}"
            else:
                line = f"[{tag}] {result_kind}, {len(raw_result)} chars of output"
            # Deduplicate identical lines (e.g., same nuclei error twice).
            if not key_findings or line != key_findings[-1]:
                key_findings.append(line)

    return {
        "attempted_actions": attempted[-20:],
        # Evidence is the model's job; we never auto-fill it.
        "evidence": [],
        "artifacts": artifacts[-15:],
        # Content-bearing snippets — filtered for signal, deduplicated.
        "key_findings": key_findings[-20:],
    }


def _classify_tool_result(content: str) -> str:
    """Classify a tool result as 'success', 'failed', or 'no_signal'."""
    if not content:
        return "no_signal"
    stripped = content.strip()
    if not stripped:
        return "no_signal"
    head = stripped[:300].lower()
    # Explicit error envelopes
    if stripped.startswith('{"error"') or '"error":' in stripped[:200]:
        return "failed"
    if any(token in head for token in (
        "traceback", "exception:", "permission denied", "command not found",
        "connection refused", "timeout", "failed", "unreachable",
    )):
        # But "failed" alone is not enough — many tools emit benign "0 failed"
        if "0 failed" in head or "no failed" in head:
            pass
        else:
            return "failed"
    return "success"


def _first_error_line(content: str) -> str:
    """Return the first non-empty line that looks like an error message."""
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        sl = s.lower()
        if any(t in sl for t in ("error", "exception", "traceback", "failed", "denied", "refused")):
            return s
    # Fallback to first non-empty line
    for line in content.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _short(text: str, n: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"
