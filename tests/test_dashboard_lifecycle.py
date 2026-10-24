"""Real isolated dashboard processes, without loading models or using port 8765."""
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/dashboard.sh"


def control(action, runtime, port, *, cwd):
    return subprocess.run(
        ["bash", str(HELPER), action, "--runtime-dir", str(runtime),
         "--port", str(port), "--device", "cpu"],
        cwd=cwd, text=True, capture_output=True, timeout=30,
    )


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_ticks(pid):
    return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux process ownership checks")
def test_real_start_status_idempotent_start_stop_from_other_directories(tmp_path):
    runtime = tmp_path / "isolated-dashboard"
    port = free_port()
    assert port != 8765
    try:
        started = control("start", runtime, port, cwd="/home")
        assert started.returncode == 0, started.stderr
        first = json.loads(started.stdout)
        assert first["running"] and first["ready"]
        assert first["device"] == "cpu"
        assert first["url"] == f"http://127.0.0.1:{port}"
        assert Path(f"/proc/{first['pid']}/cwd").resolve() == ROOT

        status = control("status", runtime, port, cwd=tmp_path)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)["pid"] == first["pid"]

        repeated = control("start", runtime, port, cwd=tmp_path)
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(repeated.stdout)["pid"] == first["pid"]
        assert (runtime / "api.token").stat().st_mode & 0o777 == 0o600

        stopped = control("stop", runtime, port, cwd="/home")
        assert stopped.returncode == 0, stopped.stderr
        absent = control("status", runtime, port, cwd=tmp_path)
        assert absent.returncode == 1
        state = json.loads(absent.stdout)
        assert not state["running"] and not state["ready"]
        assert not (runtime / "process.json").exists()
    finally:
        # This runtime directory belongs only to this test. Never control the
        # default dashboard directory or the user's service on port 8765.
        cleanup = control("stop", runtime, port, cwd=tmp_path)
        assert cleanup.returncode == 0, cleanup.stderr


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="Linux process ownership checks")
@pytest.mark.parametrize("matching_ticks", [False, True])
def test_stale_or_unowned_pid_cannot_signal_an_unrelated_process(tmp_path, matching_ticks):
    runtime = tmp_path / "isolated-dashboard"
    runtime.mkdir()
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        state = {"pid": unrelated.pid, "port": free_port(), "device": "cpu",
                 "start_ticks": start_ticks(unrelated.pid) if matching_ticks else "stale"}
        (runtime / "process.json").write_text(json.dumps(state))
        stopped = control("stop", runtime, state["port"], cwd=tmp_path)
        assert stopped.returncode == 0, stopped.stderr
        assert unrelated.poll() is None
        assert not (runtime / "process.json").exists()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_occupied_port_does_not_start_or_claim_another_service(tmp_path):
    runtime = tmp_path / "isolated-dashboard"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert port != 8765
        started = control("start", runtime, port, cwd=tmp_path)
        assert started.returncode != 0
        assert "already in use" in started.stderr
        assert not (runtime / "process.json").exists()
