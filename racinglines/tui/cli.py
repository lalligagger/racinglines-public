"""Run a `racinglines` command from inside the TUI (Data > Pull runs `racinglines data pull`), streaming its output."""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from typing import Callable

LineSink = Callable[[str], None]


def argv(*args: str) -> list[str]:
    """`racinglines ARGS` with this interpreter: the CLI is part of the same package, so it is always there."""
    return [sys.executable, "-m", "racinglines", *args]


async def run_cli(args: list[str], on_line: LineSink) -> int:
    """Run `racinglines ARGS`, streaming stdout and stderr line by line (the heartbeat, the remote-access warning and
    a sign-in URL included). Returns the exit code."""
    proc = await asyncio.create_subprocess_exec(
        *argv(*args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL, env={**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"},
    )
    assert proc.stdout is not None
    try:
        async for raw in proc.stdout:
            on_line(raw.decode(errors="replace").rstrip("\n"))
        return await proc.wait()
    finally:  # a cancelled worker or a quitting app must not leave the command running against the database
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
