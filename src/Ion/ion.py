import json
import re
import time
from typing import Any, Optional, Literal

from pydantic import BaseModel
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


def _compress_context(client, model_id: str, state: LoopState, logger=None):
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
        summary_resp = client.chat.completions.create(
            model=model_id,
            messages=summary_messages,
            max_tokens=4000,
            stream=False,
        )
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
    client,
    model_id: str,
    state: LoopState,
    tools: list[dict],
    logger=None,
    agent_name: str = "root",
):
    prefix = f"[SubAgent: {agent_name}] " if agent_name != "root" else ""
    prefix_printed = False

    # Try streaming with usage; fall back if provider doesn't support stream_options.
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=state.messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception:
        response = client.chat.completions.create(
            model=model_id,
            messages=state.messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
        )

    content_parts = []
    reasoning_content_parts = []
    tool_calls_map = {}
    finish_reason = None
    usage = None
    reasoning = False

    for chunk in response:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            # usage-only chunk when stream_options is supported
            if hasattr(chunk, "usage") and chunk.usage:
                usage = chunk.usage
            continue

        delta = choice.delta

        if delta and delta.content:
            if prefix and not prefix_printed:
                print(prefix, end="", flush=True)
                prefix_printed = True
            text = delta.content
            content_parts.append(text)
            if reasoning:
                reasoning = False
                print("\n</think>\n")
            print(text, end="", flush=True)
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
        if delta and hasattr(delta, "reasoning_content") and delta.reasoning_content:
            if prefix and not prefix_printed:
                print(prefix, end="", flush=True)
                prefix_printed = True
            text = delta.reasoning_content
            reasoning_content_parts.append(text)
            if not reasoning:
                reasoning = True
                print("<think>\n")
            print(text, end="", flush=True)

        if choice.finish_reason is not None:
            finish_reason = choice.finish_reason

    if reasoning_content_parts:
        print()
    if content_parts:
        print()

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

    if finish_reason == "tool_calls":
        tool_names = [t["function"]["name"] for t in tool_calls_data]
        exec_prefix = f"[{agent_name}] " if agent_name != "root" else ""
        print(f"{exec_prefix}🔧 Executing: {', '.join(tool_names)}")

        for tool in tool_calls_data:
            name = tool["function"]["name"]
            try:
                args = json.loads(tool["function"]["arguments"])
            except json.JSONDecodeError as e:
                # retry 3
                print(f"[ERROR]:{e}")
                continue
            except Exception as e:
                print(f"[ERROR]:{e}")
                continue
            start = time.time()

            output = dispatch(name, **args)
            duration = (time.time() - start) * 1000

            if logger:
                logger.log_tool_call(name, args, output, duration)

            state.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool["id"],
                    "content": output,
                }
            )

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


def run_agent_loop(
    client,
    model_id: str,
    state: LoopState,
    tools: list[dict],
    logger=None,
    on_before_turn=None,
    agent_name: str = "root",
):
    """
    Run the agent loop until a non-tool-calls finish reason is reached.

    Args:
        on_before_turn: Optional callback(state) invoked before each turn.
                        Can be used to refresh the system prompt with
                        updated runtime context (e.g., task graph state).
        agent_name: Identifier used for stdout prefixing (sub-agents).
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
                    _compress_context(client, model_id, state, logger)

            if on_before_turn is not None:
                on_before_turn(state)

            run_one_turn(client, model_id, state, tools, logger, agent_name=agent_name)

            # --- post-turn length handling ---
            if state.finish_reason == "length":
                # Remove the truncated assistant message before compressing
                if state.messages and state.messages[-1].get("role") == "assistant":
                    state.messages.pop()
                _compress_context(client, model_id, state, logger)
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
    client,
    model_id: str,
    state: LoopState,
    tools: list[dict],
    budget: Budget,
    logger=None,
    on_before_turn=None,
    agent_name: str = "subagent",
    stop_conditions: Optional[Any] = None,
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
                _force_final_turn(client, model_id, state, tools, logger, agent_name)
                return _extract_result(state, tracker, WhyStopped.MAX_TURNS)

            # --- pre-turn context compression ---
            if state.context_max_tokens > 0:
                estimated = _estimate_tokens(state)
                if estimated > state.context_max_tokens - 20000:
                    _compress_context(client, model_id, state, logger)

            if on_before_turn is not None:
                on_before_turn(state)

            run_one_turn(client, model_id, state, tools, logger, agent_name=agent_name)

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
                latest_content = state.messages[-1].get("content", "") or ""
            budget_violation = tracker.check_budget(
                budget, latest_content=latest_content, stop_conditions=stop_conditions
            )
            if budget_violation:
                tracker.status_transitions.append(f"budget:{budget_violation}")
                _inject_termination_message(state, budget_violation)
                _force_final_turn(client, model_id, state, tools, logger, agent_name)
                why = _map_violation_to_why(budget_violation)
                return _extract_result(state, tracker, why)

            # --- post-turn length handling ---
            if state.finish_reason == "length":
                if state.messages and state.messages[-1].get("role") == "assistant":
                    state.messages.pop()
                _compress_context(client, model_id, state, logger)
                state.finish_reason = None
                continue

            if state.finish_reason != "tool_calls":
                # Natural stop (stop, etc.)
                tracker.status_transitions.append(f"natural:{state.finish_reason}")
                return _extract_result(state, tracker, WhyStopped.SUCCESS)

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
    """Append a system message forcing the model to terminate with JSON."""
    msg = (
        f"\n[SYSTEM] Execution halted: {reason}.\n"
        "You must now output ONLY a single JSON object matching the required "
        "result schema. No additional text, no markdown fences, no explanations."
    )
    state.messages.append({"role": "system", "content": msg})


def _force_final_turn(
    client, model_id: str, state: LoopState, tools: list[dict], logger, agent_name: str
):
    """Run one final turn after forced termination to collect JSON output."""
    try:
        # Temporarily remove tools so the model can only output text
        run_one_turn(client, model_id, state, [], logger, agent_name=agent_name)
    except Exception:
        pass


def _extract_result(
    state: LoopState, tracker: SubagentLoopTracker, why: WhyStopped
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

    # If still failed but we have key findings, mark as partial
    if result.status == SubagentStatus.FAILED and result.key_findings:
        result.status = SubagentStatus.PARTIAL

    return result
