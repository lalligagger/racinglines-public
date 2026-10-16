"""`racinglines tui`: the CLI group, no heartbeat under the full-screen app, and the connection it builds (hosted with
RACINGLINES_MCP_TOKEN / RACINGLINES_MCP_URL, or `racinglines mcp` over stdio with this interpreter)."""
import sys

import pytest

from racinglines import cli
from racinglines.cli import remote
from racinglines.cli import tui as tui_cli


def _capture(monkeypatch):
    seen = {}

    def fake_run(self, *a, **k):
        seen["settings"] = self.backend.settings
        seen["warning"] = self.remote_warning
        seen["user"] = self.settings_user

    monkeypatch.setattr("racinglines.tui.app.RacinglinesApp.run", fake_run)
    return seen


def test_group_listed_and_no_heartbeat(monkeypatch, capsys):
    assert "tui" in cli.GROUPS
    started = []
    monkeypatch.setattr("racinglines.progress.start", lambda *a, **k: started.append(a))
    with pytest.raises(SystemExit) as ex:
        cli.main(["tui", "--help"])
    assert ex.value.code == 0
    assert started == []  # a heartbeat on stderr every 5 min would draw over the screen
    assert "--local" in capsys.readouterr().out


def test_hosted_with_token(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("RACINGLINES_MCP_TOKEN", "rl_test")
    monkeypatch.setenv("RACINGLINES_MCP_URL", "https://staging.example/mcp")
    monkeypatch.setattr(remote, "_warned", True)  # the stderr warning is cli/remote.py's own test
    assert tui_cli.main(["--user", "taker"]) == 0
    s = seen["settings"]
    assert (s.url, s.token, s.stdio_argv) == ("https://staging.example/mcp", "rl_test", None)
    assert seen["warning"] == remote.WARNING and seen["user"] == "taker"


def test_hosted_without_token_signs_in_first(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.delenv("RACINGLINES_MCP_TOKEN", raising=False)
    opened = []

    class FakeSession:
        def __init__(self, server):
            opened.append(server)

        def close(self):
            opened.append("closed")

    monkeypatch.setattr(remote, "Session", FakeSession)
    assert tui_cli.main(["--mcp-url", "https://x.example/mcp"]) == 0
    assert opened == ["https://x.example/mcp", "closed"]  # sign-in before the screen opens
    assert seen["settings"].token is None and seen["settings"].url == "https://x.example/mcp"


def test_hosted_sign_in_failure_exits_before_the_screen(monkeypatch, capsys):
    seen = _capture(monkeypatch)
    monkeypatch.delenv("RACINGLINES_MCP_TOKEN", raising=False)

    def refuse(server):
        raise remote.RemoteError(f"{server}: 401 Unauthorized")

    monkeypatch.setattr(remote, "Session", refuse)
    assert tui_cli.main([]) == 2
    assert "401" in capsys.readouterr().err and "settings" not in seen


def test_local_runs_racinglines_mcp_with_this_interpreter(monkeypatch):
    seen = _capture(monkeypatch)
    assert tui_cli.main(["--local", "--db", "postgresql://localhost/rl", "--no-jobs"]) == 0
    s = seen["settings"]
    assert s.stdio_argv == [sys.executable, "-m", "racinglines", "mcp", "--db", "postgresql://localhost/rl", "--no-jobs"]
    assert s.label == "local: racinglines mcp --db postgresql://localhost/rl --no-jobs"
    assert seen["warning"] is None  # local data: no remote-access warning


def test_run_cli_terminates_the_subprocess_when_cancelled(monkeypatch):
    import asyncio

    from racinglines.tui import cli as run_mod

    procs = []
    real = asyncio.create_subprocess_exec

    async def spy(*a, **k):
        proc = await real(*a, **k)
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    monkeypatch.setattr(run_mod, "argv", lambda *a: [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"])

    async def go():
        lines = []
        task = asyncio.create_task(run_mod.run_cli(["data", "pull", "f1"], lines.append))
        for _ in range(100):
            if lines:
                break
            await asyncio.sleep(0.1)
        assert lines == ["up"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return procs[0]

    proc = asyncio.run(go())
    assert proc.returncode is not None  # not left running against the database
