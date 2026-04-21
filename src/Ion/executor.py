import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from Ion.ion import LoopState, run_agent_loop
from Ion.tasks import TaskManager, Task, TaskStatus
from Ion.tools.tools import get_tools_schema


@dataclass
class TaskResult:
    task_id: str
    name: str
    success: bool
    summary: str
    full_output: str
    duration_ms: float
    attempt_count: int


@dataclass
class LayerReport:
    executed: list[TaskResult] = field(default_factory=list)
    skipped_due_to_concurrency: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "executed": [
                {
                    "task_id": r.task_id,
                    "name": r.name,
                    "success": r.success,
                    "summary": r.summary,
                    "duration_ms": round(r.duration_ms, 2),
                    "attempt_count": r.attempt_count,
                }
                for r in self.executed
            ],
            "skipped_due_to_concurrency": self.skipped_due_to_concurrency,
            "layer_summary": self._build_layer_summary(),
        }

    def _build_layer_summary(self) -> str:
        if not self.executed:
            return "No tasks were executed in this layer."
        lines = [f"Layer execution: {len(self.executed)} task(s)"]
        for r in self.executed:
            status = "SUCCESS" if r.success else "FAILED"
            lines.append(
                f"  [{status}] {r.name} ({r.task_id}) — attempt #{r.attempt_count}: {r.summary[:200]}"
            )
        return "\n".join(lines)


class TaskGraphExecutor:
    """DAG execution engine that runs ready tasks via concurrent sub-agents."""

    def __init__(
        self,
        client,
        model_id: str,
        max_concurrency: int = 3,
        max_subagent_turns: int = 20,
        context_max_tokens: int = 0,
        summarize: bool = True,
    ):
        self.client = client
        self.model_id = model_id
        self.max_concurrency = max_concurrency
        self.max_subagent_turns = max_subagent_turns
        self.context_max_tokens = context_max_tokens
        self.summarize = summarize
        self._all_schemas = get_tools_schema()

    # ------------------------------------------------------------------ #
    #  Single sub-agent wrapper                                          #
    # ------------------------------------------------------------------ #

    def _run_single_subagent(
        self,
        task: Task,
        tools_filter: Optional[list[str]] = None,
    ) -> TaskResult:
        """Run one sub-agent synchronously (meant to be called in a thread)."""
        filtered = self._all_schemas
        if tools_filter:
            filtered = [
                s
                for s in self._all_schemas
                if s.get("function", {}).get("name") in tools_filter
            ]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a tactical sub-agent of Ion. "
                    "Execute the assigned task precisely and return concise, actionable results. "
                    "Prefer structured output. Do not engage in unnecessary conversation."
                ),
            },
            {"role": "user", "content": task.description},
        ]
        state = LoopState(
            messages=messages,
            max_turns=self.max_subagent_turns,
            context_max_tokens=self.context_max_tokens,
        )

        start = time.time()
        try:
            run_agent_loop(self.client, self.model_id, state, filtered)
            content = (
                state.messages[-1].get("content", "")
                if state.messages
                else "(no output)"
            )
            success = state.finish_reason not in ("max_turns_reached", "length")
        except Exception as e:
            content = f"Subagent error: {e}"
            success = False

        duration = (time.time() - start) * 1000

        # Summarize if output is long and summarization is enabled
        if self.summarize and len(content) > 2000:
            summary = self._summarize_output(content)
        else:
            summary = content

        return TaskResult(
            task_id=task.id,
            name=task.name,
            success=success,
            summary=summary,
            full_output=content,
            duration_ms=duration,
            attempt_count=task.attempt_count,
        )

    def _summarize_output(self, content: str) -> str:
        """Use a quick LLM call to summarize lengthy sub-agent output."""
        try:
            resp = self.client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize the following sub-agent execution output into a "
                            "structured report with these sections:\n"
                            "1. Key Findings (bullet points)\n"
                            "2. Conclusion (1-2 sentences)\n"
                            "3. State (completed / blocked / failed)\n"
                            "4. Recommended Next Steps\n"
                            "Be concise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": content[:15000],
                    },
                ],
                max_tokens=800,
                stream=False,
            )
            return resp.choices[0].message.content or content[:500]
        except Exception:
            # Fallback: truncate with ellipsis
            return content[:1500] + "\n...[truncated]"

    # ------------------------------------------------------------------ #
    #  Layer execution                                                   #
    # ------------------------------------------------------------------ #

    async def execute_layer(
        self,
        task_manager: TaskManager,
        tools_filter: Optional[list[str]] = None,
    ) -> LayerReport:
        """Execute all ready tasks concurrently, update their status, return a report."""
        ready = task_manager.get_ready_tasks()
        if not ready:
            return LayerReport()

        # Mark selected tasks as running
        for task in ready:
            task_manager.update_status(task.id, TaskStatus.RUNNING)

        # Cap concurrency
        to_run = ready[: self.max_concurrency]
        skipped = [t.id for t in ready[self.max_concurrency :]]

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            futures = [
                loop.run_in_executor(
                    pool, self._run_single_subagent, task, tools_filter
                )
                for task in to_run
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)

        report = LayerReport(skipped_due_to_concurrency=skipped)
        for task, result in zip(to_run, results):
            if isinstance(result, BaseException):
                result = TaskResult(
                    task_id=task.id,
                    name=task.name,
                    success=False,
                    summary=f"Execution exception: {result}",
                    full_output=str(result),
                    duration_ms=0.0,
                    attempt_count=task.attempt_count,
                )
            # Persist status + result into task manager
            final_status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            task_manager.update_status(task.id, final_status, result=result.summary)
            report.executed.append(result)

        return report

    # ------------------------------------------------------------------ #
    #  Full-graph auto-run (optional)                                    #
    # ------------------------------------------------------------------ #

    async def run_until_complete(
        self,
        task_manager: TaskManager,
        tools_filter: Optional[list[str]] = None,
        max_layers: int = 50,
    ) -> dict:
        """Auto-execute the task graph layer by layer until no ready tasks remain."""
        layer_reports = []
        for _ in range(max_layers):
            report = await self.execute_layer(task_manager, tools_filter)
            if not report.executed and not report.skipped_due_to_concurrency:
                break
            layer_reports.append(report.to_dict())
            # If there were skipped tasks, they will be picked up in the next iteration
            if report.skipped_due_to_concurrency:
                await asyncio.sleep(0.1)

        remaining = task_manager.get_ready_tasks()
        failed = task_manager.get_failed_tasks()
        return {
            "layers_executed": len(layer_reports),
            "layer_reports": layer_reports,
            "remaining_ready_tasks": len(remaining),
            "failed_tasks": [
                {"id": t.id, "name": t.name, "attempts": t.attempt_count}
                for t in failed
            ],
        }
