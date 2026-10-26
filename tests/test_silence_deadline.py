import os
import subprocess
import sys
import time

import pytest

from polyctl import cli, procs

pytestmark = pytest.mark.skipif(os.name == "nt", reason="a process group's CPU is not readable on Windows")


def _spawn(code):
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)


def test_a_silent_reviewer_is_killed_as_stalled_and_a_thinking_one_is_left_to_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "REVIEW_HEARTBEAT_SECONDS", 0.2)
    quiet = _spawn("import time; print('partial answer', flush=True); time.sleep(120)")
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired) as raised:
            cli._reviewer_communicate(quiet, 120, "quiet", started, stall=1.0)
    finally:
        quiet.kill()
        quiet.communicate()
    assert raised.value.stalled >= 1.0 and time.monotonic() - started < 60

    done = tmp_path / "done"
    busy = _spawn(f"import os, pathlib\ndone = pathlib.Path({str(done)!r})\nwhile not done.exists():\n    pass\n"
                  "os.write(1, b'verdict\\n')\ndone.unlink()\nos._exit(0)")
    try:
        warmup = time.monotonic()
        base = procs.group_cpu_seconds(busy.pid)
        current = base
        while (base is None or current is None or current <= base + 0.02) and time.monotonic() - warmup < 60:
            time.sleep(0.05)
            reading = procs.group_cpu_seconds(busy.pid)
            if base is None:
                base = reading
            current = reading
        step = time.monotonic() - warmup
        stall = max(1.0, step * 2)
        timeout = max(120.0, stall * 20)
        real_cpu = procs.group_cpu_seconds
        busy_started = time.monotonic()
        seen = []

        def _observed_cpu(pgid):
            cpu = real_cpu(pgid)
            if pgid == busy.pid and seen and not done.exists():
                wait_until = time.monotonic() + timeout
                while cpu is not None and cpu <= seen[-1] + 0.01 and time.monotonic() < wait_until:
                    time.sleep(0.05)
                    cpu = real_cpu(pgid)
            if pgid == busy.pid and cpu is not None and (not seen or cpu > seen[-1] + 0.01):
                seen.append(cpu)
                if len(seen) >= 3 and time.monotonic() - busy_started >= stall and not done.exists():
                    done.write_text("ok", encoding="utf-8")
                    wait_until = time.monotonic() + timeout
                    while done.exists() and time.monotonic() < wait_until:
                        time.sleep(0.01)
            return cpu

        monkeypatch.setattr(procs, "group_cpu_seconds", _observed_cpu)
        out, _ = cli._reviewer_communicate(busy, timeout, "busy", busy_started, stall=stall)
    finally:
        busy.kill()
        busy.communicate()
    assert out.strip() == "verdict" and len(seen) >= 3


def test_the_cpu_of_a_process_group_is_read_as_it_is_spent(tmp_path):
    done = tmp_path / "done"
    busy = _spawn(f"import os, pathlib\ndone = pathlib.Path({str(done)!r})\nwhile not done.exists():\n    pass\n"
                  "os._exit(0)")
    try:
        first = procs.group_cpu_seconds(busy.pid)
        second = first
        deadline = time.monotonic() + 60
        while (first is None or second is None or second <= first) and time.monotonic() < deadline:
            time.sleep(0.05)
            reading = procs.group_cpu_seconds(busy.pid)
            if first is None:
                first = reading
            second = reading
        done.write_text("ok", encoding="utf-8")
    finally:
        busy.kill()
        busy.communicate()
    assert first is not None and second is not None and second > first
    assert procs.group_cpu_seconds(2 ** 22 - 3) is None
