"""main._supervised's exit status: the one thing a process supervisor or cron
reads. Each case runs in a subprocess, since main.py configures logging (and
opens scraper.log) at import, and the point is the process's own exit code."""

import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent


def run_supervised(body: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = f"import asyncio, main\n\nasync def job():\n    {body}\n\nmain._supervised(job())\n"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PYTHONPATH": str(AGENT_DIR)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_a_hunter_that_died_exits_non_zero(tmp_path):
    # a supervisor that restarts on failure only restarts what says it failed
    result = run_supervised('raise ConnectionError("connection refused")', tmp_path)
    assert result.returncode == 1
    assert "Hunter stopped: connection refused" in result.stderr


def test_a_run_that_finished_exits_zero(tmp_path):
    assert run_supervised("return None", tmp_path).returncode == 0


def test_a_stop_signal_is_a_clean_exit(tmp_path):
    result = run_supervised("raise asyncio.CancelledError", tmp_path)
    assert result.returncode == 0
    assert "Stopped by signal" in result.stderr
