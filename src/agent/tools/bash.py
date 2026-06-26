"""Run a shell command (streamed output; timeout; kill process tree). Port: tools/bash.ts."""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult, truncate_tail


class BashArgs(BaseModel):
    command: str = Field(description="The shell command to run.")
    timeout: float | None = Field(
        default=None, description="Optional timeout in seconds (no limit by default)."
    )


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a shell command in the working directory and return its combined "
        "stdout/stderr. Output is truncated if very large. Optionally set a timeout."
    )
    parameters = BashArgs
    prompt_snippet = "bash: Run a shell command"

    @classmethod
    def permission_target(cls, args: dict) -> str:
        return str(args.get("command", ""))

    async def execute(self, args: BashArgs, *, on_update=None) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                args.command,
                cwd=str(self.cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # own process group, so we can kill the whole tree
            )
        except OSError as exc:
            return ToolResult(content=f"Failed to start command: {exc}", is_error=True)

        chunks: list[str] = []

        async def pump() -> None:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                chunks.append(text)
                if on_update is not None:
                    on_update(text)
            await proc.wait()

        try:
            if args.timeout:
                await asyncio.wait_for(pump(), timeout=args.timeout)
            else:
                await pump()
        except asyncio.TimeoutError:
            self._kill(proc)
            output, _ = truncate_tail("".join(chunks))
            return ToolResult(
                content=(output or "(no output)") + f"\n\n[timed out after {args.timeout}s]",
                is_error=True,
            )
        except asyncio.CancelledError:
            self._kill(proc)
            raise  # propagate cancellation (e.g. user aborted the turn)

        output, truncated = truncate_tail("".join(chunks))
        code = proc.returncode
        suffix = ""
        if truncated:
            suffix += "\n\n[output truncated]"
        if code:
            suffix += f"\n\n[exit code {code}]"
        return ToolResult(content=(output or "(no output)") + suffix, is_error=bool(code))

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
