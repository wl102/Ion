import asyncio
import logging
import os

from .registry import registry, tool_error, tool_result


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _bash_exec(command: str) -> str:
    """Run a shell command in the current workspace with safety checks."""

    forbidden_patterns = [
        "rm -rf",
        "shutdown",
        "reboot",
        "mkfs",
        "dd if=",
        "> /dev/",
        "chmod -R 777",
        "killall",
        "pkill",
    ]

    lower_cmd = command.lower()
    if any(p in lower_cmd for p in forbidden_patterns):
        return tool_error("Dangerous command blocked")

    timeout = float(os.getenv("BASH_COMMAND_TIMEOUT", 120))

    output_lines: list[str] = []

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=os.getcwd(),
        )

        async def read_stream():
            while True:
                if process.stdout is None:
                    break

                line = await process.stdout.readline()
                if not line:
                    break

                output_lines.append(line.decode("utf-8", errors="replace"))

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stream(), process.wait()), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

            return tool_error(f"Execution timeout: exceeded {timeout}s")

        return_code = process.returncode

        full_output = "".join(output_lines).strip() or "(no output)"

        if return_code != 0:
            fix_suggestion = ""

            lower_out = full_output.lower()

            if "not found" in lower_out:
                fix_suggestion = (
                    "Command not found. Verify that the binary is installed and available in PATH, "
                    "or use an absolute path to the executable."
                )
            elif "permission denied" in lower_out:
                fix_suggestion = (
                    "Permission denied. Check file permissions or try running without privileged operations. "
                    "Avoid using sudo in restricted environments."
                )

            return tool_result(
                success=False,
                output=full_output,
                exit_code=return_code,
                fix_suggestion=fix_suggestion,
            )

        return tool_result(success=True, output=full_output)

    except Exception as e:
        logger.exception("shell_exec internal error")
        return tool_error(f"exec error: {type(e).__name__}")


# ---------------------------------------------------------------------------
# Inline schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

BASH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command in the current workspace with safety checks.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "bash command to execute"}
            },
            "required": ["command"],
        },
    },
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

registry.register(
    name="bash",
    toolset="builtin",
    schema=BASH_SCHEMA,
    handler=_bash_exec,
    is_async=True,
    description="Run a shell command in the current workspace with safety checks.",
    emoji="🖥️",
    max_result_size_chars=20000,
)
