import json
import time
from typing import Optional, Literal

from pydantic import BaseModel
from Ion.tools.tools import dispatch


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str]


class LoopState(BaseModel):
    messages: list[dict]
    turn_count: int = 0
    finish_reason: Optional[str] = None


def run_one_turn(
    client, model_id: str, state: LoopState, tools: list[dict], logger=None
):
    response = client.chat.completions.create(
        model=model_id,
        messages=state.messages,
        tools=tools,
        tool_choice="auto",
        stream=False,
    )
    msg = response.choices[0].message

    tool_calls_data = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls_data.append(tc.model_dump())

    assistant_message = {
        "role": "assistant",
        "content": msg.content,
    }
    if tool_calls_data:
        assistant_message["tool_calls"] = tool_calls_data
    state.messages.append(assistant_message)

    if response.choices[0].finish_reason == "tool_calls":
        for tool in msg.tool_calls if msg.tool_calls else []:
            name = tool.function.name
            args = json.loads(tool.function.arguments)

            start = time.time()

            output = dispatch(name, **args)
            duration = (time.time() - start) * 1000

            if logger:
                logger.log_tool_call(name, args, output, duration)

            state.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool.id,
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )

    state.turn_count += 1
    state.finish_reason = response.choices[0].finish_reason

    if logger and hasattr(response, "usage") and response.usage:
        logger.record_token_usage(response.usage.model_dump())


def run_agent_loop(
    client, model_id: str, state: LoopState, tools: list[dict], logger=None
):
    while True:
        run_one_turn(client, model_id, state, tools, logger)
        if state.finish_reason != "tool_calls":
            return
