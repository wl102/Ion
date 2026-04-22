import json
import time
from typing import Optional, Literal

from pydantic import BaseModel
from Ion.tools.registry import dispatch


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
    client, model_id: str, state: LoopState, tools: list[dict], logger=None, agent_name: str = "root"
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
    tool_calls_map = {}
    finish_reason = None
    usage = None

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

        if choice.finish_reason is not None:
            finish_reason = choice.finish_reason

    if content_parts:
        print()

    content = "".join(content_parts)
    tool_calls_data = list(tool_calls_map.values())

    assistant_message = {
        "role": "assistant",
        "content": content or None,
    }
    if tool_calls_data:
        assistant_message["tool_calls"] = tool_calls_data
    state.messages.append(assistant_message)

    if finish_reason == "tool_calls":
        for tool in tool_calls_data:
            name = tool["function"]["name"]
            args = json.loads(tool["function"]["arguments"])

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
