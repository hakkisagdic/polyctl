"""The watchdog starts one bounded catch-up when it is switched on and due.

The child is the same stand-in the hunt schedule uses: World records `Popen` argv and starts no
process, so no reviewer and no model run. Checks 1 to 7 of the scheduled catch-up.
"""
import json
import os
import re
import sys

import pytest

from polyctl import lib as A, watchdog as W
from tests.scenarios import World

UNSEEN = (".claude/settings.json", "modified", "ab" * 32)
HEADER = re.compile(r"=== \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} catchup ===")


def _world(project, monkeypatch, tmp_path, record_notify=False):
    real = W.notify
    world = World(project, monkeypatch, tmp_path)
    if record_notify:
        monkeypatch.setattr(W, "notify", real)
    return world


def _settings(root, every_hours, limit=1):
    path = os.path.join(root, ".polyctl", "config.json")
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["catchup"] = {"every_hours": every_hours, "limit": limit}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


def _waiver(root):
    return A.waive(root, "review", "B7", "the reviewer was down", by="ada")


def _catchups(world):
    return [argv for argv in world.spawned if isinstance(argv, list) and "catchup" in argv]


def _catchup_names(root):
    if not os.path.isdir(W.STATE_DIR):
        return []
    return [name for name in os.listdir(W.STATE_DIR) if name.startswith("catchup-")]


def _failed(root):
    return [row for row in A.notices(root, limit=400, include_suppressed=True)
            if row.get("key") == "catchup-failed"]


def _prepare(world, every_hours, limit=1, waiver=True):
    _settings(world.root, every_hours, limit)
    if waiver:
        _waiver(world.root)
    return world


def test_a_live_cycle_with_catchup_every_hours_0_starts_nothing(project, monkeypatch, tmp_path):
    """Check 1: the default starts no child and does not read the waiver file."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 0)
    calls = []
    real = A.open_waivers

    def wrapped(root, gate=None, slice_id=None):
        calls.append(root)
        return real(root, gate=gate, slice_id=slice_id)

    monkeypatch.setattr(A, "open_waivers", wrapped)

    trace = world.cycle(dry_run=False)

    assert calls == []
    assert _catchups(world) == [] and _catchup_names(world.root) == []
    assert "catch-up" not in "\n".join(trace)
    assert "last_catchup" not in W.load_state(world.root)


def test_a_due_cycle_starts_one_bounded_catchup(project, monkeypatch, tmp_path):
    """Check 2: one detached `catchup --limit 1`, a log header, and the cycle says it started."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6)
    root = os.path.abspath(world.root)

    trace = world.cycle(dry_run=False)

    argv, = _catchups(world)
    assert argv[-5:] == ["-C", root, "catchup", "--limit", "1"]
    assert "--by" not in argv and "--author-family" not in argv
    assert "started a bounded catch-up" in trace
    text = open(W._catchup_log_path(world.root), encoding="utf-8").read()
    assert HEADER.search(text)
    state = W.load_state(world.root)
    assert state.get("catchup_pid") and state.get("last_catchup")


def test_a_cycle_a_minute_later_starts_no_second_catchup(project, monkeypatch, tmp_path):
    """Check 3: `last_catchup` from the run a moment ago holds the next cycle."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6)
    world.cycle(dry_run=False)
    world.spawned.clear()
    log = W._catchup_log_path(world.root)
    headers = HEADER.findall(open(log, encoding="utf-8").read())

    trace = world.cycle(dry_run=False)

    assert _catchups(world) == []
    assert "started a bounded catch-up" not in trace
    assert HEADER.findall(open(log, encoding="utf-8").read()) == headers


def test_a_cycle_with_no_open_waiver_starts_nothing_and_prints_nothing(project, monkeypatch, tmp_path):
    """Check 4: the setting is on, and an empty waiver list starts nothing and prints nothing."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6, waiver=False)

    trace = world.cycle(dry_run=False)

    assert _catchups(world) == [] and _catchup_names(world.root) == []
    assert "catch-up" not in "\n".join(trace)
    assert "last_catchup" not in W.load_state(world.root)


def test_unseen_harness_configuration_holds_the_catchup_and_prints_the_reason(project, monkeypatch, tmp_path):
    """Check 5: harness configuration nobody has seen prints the reason and starts nothing, as a hunt does."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6)
    world.harness_unseen = [UNSEEN]

    trace = world.cycle(dry_run=False)

    assert _catchups(world) == [] and _catchup_names(world.root) == []
    assert any("harness configuration nobody has seen" in line and line.endswith("not starting a catch-up")
               for line in trace)
    assert "last_catchup" not in W.load_state(world.root)


def test_a_dry_cycle_starts_nothing_and_writes_no_catchup_state(project, monkeypatch, tmp_path):
    """Check 6: `--dry-run` says it would start a catch-up, starts nothing, and writes no state."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6)
    state_path = W.state_path(world.root)
    before = open(state_path, encoding="utf-8").read() if os.path.exists(state_path) else None

    trace = world.cycle(dry_run=True)

    after = open(state_path, encoding="utf-8").read() if os.path.exists(state_path) else None
    assert "would start a catch-up" in trace
    assert "started a bounded catch-up" not in trace
    assert _catchups(world) == [] and _catchup_names(world.root) == []
    assert before == after
    assert "last_catchup" not in W.load_state(world.root) and "catchup_pid" not in W.load_state(world.root)


def test_a_catchup_that_exits_1_tells_a_person_once_within_six_hours(project, monkeypatch, tmp_path,
                                                                    desktop_notifications):
    """Check 7: exit 1 records one `catchup-failed` alarm to a person; a later cycle adds no second."""
    world = _prepare(_world(project, monkeypatch, tmp_path, record_notify=True), 6)
    root = world.root
    world.cycle(dry_run=False)
    with open(W._catchup_log_path(root), "a", encoding="utf-8") as fh:
        fh.write("gate re-run failed\n")
    with open(W._catchup_status_path(root), "w", encoding="utf-8") as fh:
        fh.write("1\n")
    monkeypatch.setattr(W, "_pid_exists", lambda pid: False)

    world.cycle(dry_run=False)

    failed = _failed(root)
    assert len(failed) == 1 and failed[0]["sent"] is True and failed[0]["msg"] == "gate re-run failed"
    alarms = [alarm for alarm in A.active_alarms(A.project_key(root)) if alarm["key"] == "catchup-failed"]
    assert len(alarms) == 1 and alarms[0]["count"] == 1
    assert [title for title, _msg in desktop_notifications if "catch-up failed" in title] == [
        f"{A.project_key(root)}: catch-up failed"]
    world.spawned.clear()

    world.cycle(dry_run=False)

    assert _failed(root) == failed
    assert [alarm["count"] for alarm in A.active_alarms(A.project_key(root)) if alarm["key"] == "catchup-failed"] == [1]
    assert _catchups(world) == []
    assert len([title for title, _msg in desktop_notifications if "catch-up failed" in title]) == 1


def test_exit_3_waits_out_the_interval_and_raises_no_alarm(project, monkeypatch, tmp_path, desktop_notifications):
    """Exit 3 leaves `last_catchup` in place, so the next cycle does not start another or tell a person."""
    world = _prepare(_world(project, monkeypatch, tmp_path, record_notify=True), 6)
    root = world.root
    world.cycle(dry_run=False)
    started = W.load_state(root)["last_catchup"]
    with open(W._catchup_status_path(root), "w", encoding="utf-8") as fh:
        fh.write("3\n")
    monkeypatch.setattr(W, "_pid_exists", lambda pid: False)
    world.spawned.clear()

    world.cycle(dry_run=False)

    assert _catchups(world) == [] and _failed(root) == []
    assert [title for title, _msg in desktop_notifications if "catch-up failed" in title] == []
    assert W.load_state(root).get("last_catchup") == started and "catchup_pid" not in W.load_state(root)


def test_a_reused_pid_does_not_count_as_the_scheduled_catchup(project, monkeypatch, tmp_path):
    """A live pid whose command is not this schedule's catch-up does not hold the next one."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6, limit=2)
    root = os.path.abspath(world.root)
    state = W.load_state(world.root)
    state.update(catchup_pid=os.getpid(), last_catchup=0)
    W.save_state(world.root, state)
    monkeypatch.setattr(W, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(W, "_process_zombie", lambda pid: False)
    monkeypatch.setattr(W, "_process_command", lambda pid: f"{sys.executable} -m pytest")

    trace = world.cycle(dry_run=False)

    argv, = _catchups(world)
    assert argv[-5:] == ["-C", root, "catchup", "--limit", "2"]
    assert "--by" not in argv and "--author-family" not in argv
    assert "started a bounded catch-up" in trace


def test_a_live_scheduled_catchup_blocks_another(project, monkeypatch, tmp_path):
    """A pid that is still the catch-up this schedule started blocks another, even when the interval has passed."""
    world = _prepare(_world(project, monkeypatch, tmp_path), 6)
    root = os.path.abspath(world.root)
    state = W.load_state(world.root)
    state.update(catchup_pid=os.getpid(), last_catchup=0)
    W.save_state(world.root, state)
    monkeypatch.setattr(W, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(W, "_process_zombie", lambda pid: False)
    monkeypatch.setattr(W, "_process_command",
                        lambda pid: f"{sys.executable} -m polyctl -C {root} catchup --limit 1")

    trace = world.cycle(dry_run=False)

    assert _catchups(world) == []
    assert "started a bounded catch-up" not in trace and "would start a catch-up" not in trace
    assert W.load_state(world.root).get("catchup_pid") == os.getpid()


@pytest.mark.skipif(os.name == "nt", reason="signal 0 is not a probe on Windows")
def test_a_pid_check_asks_with_signal_0_and_stops_nothing(monkeypatch):
    """The schedule asks whether a pid exists and never signals it."""
    asked = []

    def kill(pid, sig):
        asked.append(sig)
        raise OSError("gone")

    monkeypatch.setattr(os, "kill", kill)

    assert W._pid_exists(12345) is False
    assert asked == [0]
