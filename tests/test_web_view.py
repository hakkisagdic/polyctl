"""`polyctl watch --web`: the panel, the board, the pipeline and the fleet as read-only pages and JSON endpoints on 127.0.0.1 (WEB-VIEW, WEB-API).

Each test starts the server as the command line does, `polyctl watch --web --port 0`, in a thread
against a temporary project, and reads it the way a browser or a local program does.
"""
import hashlib
import html
import http.client
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyctl import cli, lib as A, web

BOARD = """# Board

## running
- [W1] the page

## blocked
- [W2] a question for the owner · needs: the owner's answer

## queued
- [W3] <script>alert(1)</script> after the page · needs: W1

## verified

## done
"""
URGENT = "20260926-0900-fable-to-kiro-DECISION-stop.md"


@pytest.fixture
def start(project, monkeypatch):
    """start(*words) runs `polyctl -C <project> watch --web --port 0 <words>` in a thread and returns once it serves.

    What comes back holds the port it listens on and the exit status the command returns once
    the server is shut down, which happens after the test. Serving is known from an answer to a
    path that is no page, so no page is computed before the test asks for one, and the line the
    command prints before it serves has been printed.
    """
    monkeypatch.setattr(A, "quota", lambda adapter, ttl=300: [])   # no real keyflip: the panel asks it for the quota
    monkeypatch.setattr(A, "all_workspaces", lambda: [{"path": project["root"], "mtime": time.time()}])
    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    Path(project["root"], ".polyctl", "board.md").write_text(BOARD, encoding="utf-8")
    listening, running = [], []
    listen = web.listen

    def recorded(*args, **kwargs):
        listening.append(listen(*args, **kwargs))
        return listening[-1]

    monkeypatch.setattr(web, "listen", recorded)

    def run(*words):
        view = SimpleNamespace(exits=[])
        argv = ["-C", project["root"], "watch", "--web", "--port", "0", *words]
        thread = threading.Thread(target=lambda: view.exits.append(cli.main(argv)), daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while len(listening) <= len(running) and thread.is_alive() and time.monotonic() < deadline:
            thread.join(0.01)
        assert len(listening) > len(running), f"polyctl watch --web exited {view.exits} before it listened"
        view.server, view.thread = listening[-1], thread
        view.port = view.server.server_port
        running.append(view)
        assert _request(view.port, "/not-a-page")[0] == 404
        return view

    yield run
    for view in running:
        view.server.shutdown()
        view.thread.join(10)


def _request(port, path="/", method="GET", host=None, body=None):
    """(status, headers, text) of one request, as a browser would make it."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request(method, path, body=body, headers={"Host": host} if host else {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode("utf-8")
    finally:
        connection.close()


def _text(page):
    """What a page shows inside its <pre>, as plain text."""
    return html.unescape(re.sub(r"<[^>]+>", "", re.search(r"<pre>(.*)</pre>", page, re.S).group(1)))


def _files(*roots):
    """Every file under these directories but a git directory, with its bytes."""
    return {str(path): path.read_bytes() for root in roots for path in sorted(Path(root).rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(root).parts}


def _tree_digest(root):
    """One SHA-256 digest of every file and directory under `root`, `.git` included."""
    digest = hashlib.sha256()
    base = Path(root)
    if not base.exists():
        return digest.hexdigest()
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big") + rel)
        if path.is_symlink():
            target = os.readlink(path).encode("utf-8")
            digest.update(b"L" + len(target).to_bytes(4, "big") + target)
        elif path.is_file():
            data = path.read_bytes()
            digest.update(b"F" + len(data).to_bytes(8, "big") + data)
        elif path.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def test_the_panel_the_board_the_pipeline_and_the_fleet_are_pages_that_refresh_themselves(start, capsys):
    view = start("--interval", "5")
    routes = ("/", "/board", "/pipeline", "/fleet")

    pages = {path: _request(view.port, path) for path in routes}

    for path, (status, headers, page) in pages.items():
        assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8", path
        assert '<meta http-equiv="refresh" content="5">' in page, path
        assert all(f'<a href="{other}"' in page for other in routes), path
        assert page.count(' aria-current="page">') == 1 and f'<a href="{path}" aria-current="page">' in page, path
        assert "<title>proj · " in page, path
    panel, board, pipeline, fleet = (_text(pages[path][2]) for path in routes)
    assert "PROJ" in panel and "REPOSITORY" in panel and "Board:   1 running · 1 blocked · 1 queued" in panel
    assert "RUNNING (1)" in board and "W2  a question for the owner   needs: the owner's answer" in board
    assert "waiting" in pipeline and "with a person" in pipeline and "W1" in pipeline and "W2" in pipeline
    assert "ALL PROJECTS" in fleet and re.search(r"proj\s+unknown", fleet)
    assert f"polyctl watch --web: http://127.0.0.1:{view.port}/  read-only" in capsys.readouterr().out


def test_with_all_the_address_it_prints_is_the_fleet(start, capsys):
    view = start("--all")

    assert f"polyctl watch --web: http://127.0.0.1:{view.port}/fleet  read-only" in capsys.readouterr().out
    assert _request(view.port, "/fleet")[0] == 200


def test_the_board_page_is_the_text_polyctl_board_prints_banner_and_all(start, project, capsys):
    Path(project["root"], project["mailbox"], URGENT).write_text("# stop W1\n\n## URGENT\n", encoding="utf-8")
    view = start()
    capsys.readouterr()

    page = _request(view.port, "/board")[2]
    cli.cmd_board(project, SimpleNamespace(view=None))

    printed = capsys.readouterr().out
    assert printed.startswith("URGENT for the implementer: stop W1") and "QUEUED (1)" in printed
    assert _text(page) == printed.rstrip("\n")


def test_a_board_title_is_shown_as_text_and_the_page_may_run_no_script(start):
    view = start()

    status, headers, page = _request(view.port, "/board")

    assert status == 200 and "&lt;script&gt;alert(1)&lt;/script&gt; after the page" in page
    assert "<script" not in page
    assert headers["Content-Security-Policy"].startswith("default-src 'none'; style-src 'unsafe-inline'")
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"


def test_every_method_but_get_is_refused_and_changes_nothing(start, project):
    view = start()
    before = _files(project["root"])

    for path in ("/board", "/pipeline", "/api/status", "/api/board", "/api/pipeline", "/api/fleet"):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "PROPFIND"):
            body = b"- [X] added over http" if method in ("POST", "PUT", "PATCH") else None

            status, headers, text = _request(view.port, path, method, body=body)

            assert status == 405 and headers["Allow"] == "GET", (path, method)
            assert headers["Content-Security-Policy"] == web.CSP, (path, method)
            assert text == ("" if method == "HEAD"
                            else "polyctl watch --web is read-only: it answers GET and nothing else.\n")

    assert _files(project["root"]) == before
    assert _request(view.port, "/board")[0] == 200


def test_a_request_addressed_to_another_host_is_refused(start):
    view = start()

    status, _, text = _request(view.port, "/", host=f"attacker.example:{view.port}")

    assert status == 403 and f"localhost:{view.port}" in text and "<pre>" not in text
    assert _request(view.port, "/", host=f"localhost:{view.port}")[0] == 200
    assert _request(view.port, "/nowhere")[0] == 404


def test_nothing_but_a_loopback_address_is_bound():
    for host in ("0.0.0.0", "192.0.2.10", "localhost", "::1", ""):
        with pytest.raises(ValueError, match="loopback"):
            web.listen({}, "proj", 15, 0, host=host)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["watch", "--web", "--host", "0.0.0.0"])     # no option names another address

    server = web.listen({}, "proj", 15, 0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_a_page_marks_no_message_seen_and_writes_nothing_where_polyctl_board_marks_it_seen(start, project):
    Path(project["root"], project["mailbox"], URGENT).write_text("# stop W1\n\n## URGENT\n", encoding="utf-8")
    A.project_key(project["root"])          # a project is named the first time any command looks at it (#66)
    view = start()
    before = _files(project["root"], A.HOME)

    shown = [_text(_request(view.port, path)[2]) for path in ("/", "/board", "/fleet")]

    assert "URGENT for the implementer: stop W1" in shown[0] and "URGENT for the implementer: stop W1" in shown[1]
    assert _files(project["root"], A.HOME) == before
    assert [row for row in A.mail_log(project["root"]) if row.get("event") == "seen"] == []

    cli.cmd_board(project, SimpleNamespace(view=None))       # the terminal command shows it to its reader

    assert [(row["id"], row["by"]) for row in A.mail_log(project["root"]) if row.get("event") == "seen"] == \
        [(URGENT, "person")]


def test_a_page_that_cannot_be_computed_says_so_and_the_others_still_serve(start, monkeypatch, capsys):
    def broken(width=None):
        raise RuntimeError("the store\nis gone")

    monkeypatch.setattr(cli, "render_fleet", broken)
    monkeypatch.delenv("POLYCTL_DEBUG", raising=False)
    view = start()

    status, _, page = _request(view.port, "/fleet")

    assert status == 500 and "this page could not be computed: RuntimeError: the store is gone" in page
    assert '<meta http-equiv="refresh"' in page
    assert "polyctl watch --web: /fleet: RuntimeError: the store is gone" in capsys.readouterr().err
    assert _request(view.port, "/")[0] == 200


def test_the_panels_colours_become_classes_and_no_escape_reaches_the_page(start, monkeypatch):
    assert web.ansi_html("\x1b[1m\x1b[36m══\x1b[0m plain \x1b[2mdim <b>&\x1b[0m\x1b[?25l\x07end") == \
        '<span class="b cyan">══</span> plain <span class="dim">dim &lt;b&gt;&amp;</span>end'
    monkeypatch.setattr(A, "colour_enabled", lambda stream=None: True)      # as when started from a terminal
    view = start()

    page = _request(view.port, "/")[2]

    assert '<span class="b cyan">═══' in page and "\x1b" not in page


def test_the_stopped_server_ends_the_command_with_0(start):
    view = start()

    view.server.shutdown()
    view.thread.join(10)

    assert view.exits == [0]


def test_a_port_without_web_a_port_out_of_range_a_busy_port_and_a_zero_interval_are_refused(project, capsys):
    root = project["root"]
    assert cli.main(["-C", root, "watch", "--port", "9000"]) == 2
    assert "--port is the port of --web" in capsys.readouterr().err
    assert cli.main(["-C", root, "watch", "--web", "--port", "70000"]) == 2
    assert "a port is 0 to 65535" in capsys.readouterr().err
    assert cli.main(["-C", root, "watch", "--web", "--port", "0", "--interval", "0"]) == 2
    assert "a page refreshes at most once a second" in capsys.readouterr().err

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        assert cli.main(["-C", root, "watch", "--web", "--port", str(port)]) == 1
    assert f"cannot listen on 127.0.0.1:{port}" in capsys.readouterr().err


def test_the_json_endpoints_serve_what_the_pages_show_with_schema_version(start, project, monkeypatch):
    view = start()
    cfg = A.load_config(project["root"], record=False)
    expected = {
        "/api/status": cli.status_facts(cfg, 8, shown=False),
        "/api/board": cli.board_facts(cfg, shown=False),
        "/api/pipeline": A.pipeline_facts(cfg),
        "/api/fleet": cli.fleet_facts(),
    }

    for path, direct in expected.items():
        status, headers, raw = _request(view.port, path)

        assert status == 200, path
        assert headers["Content-Type"] == "application/json; charset=utf-8", path
        assert headers["Content-Security-Policy"] == web.CSP, path
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff", path
        assert headers["Referrer-Policy"] == "no-referrer", path
        payload = json.loads(raw)
        assert list(payload)[0] == "schema_version" and payload["schema_version"] == 1, path
        assert set(payload) == {"schema_version", *direct}, path
        for key, value in direct.items():
            if key == "at":
                assert isinstance(payload["at"], int), path
            else:
                assert payload[key] == value, (path, key)

    status, _, text = _request(view.port, "/api/status", host=f"attacker.example:{view.port}")
    assert status == 403 and f"localhost:{view.port}" in text

    monkeypatch.setattr(cli, "fleet_facts", lambda: (_ for _ in ()).throw(RuntimeError("fleet\nunreadable")))
    status, headers, raw = _request(view.port, "/api/fleet")
    assert status == 500 and headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(raw) == {"schema_version": 1, "error": "RuntimeError: fleet unreadable"}
    assert _request(view.port, "/api/status")[0] == 200


def test_the_pipeline_page_places_each_slice_in_its_column_and_shows_person_steps_as_command_text_only(start, project):
    root = Path(project["root"])
    (root / ".polyctl" / "board.md").write_text(
        "# Board\n\n"
        "## running\n"
        "- [W1] review in flight\n\n"
        "## blocked\n"
        "- [W2] waiting on owner · waiting: human · needs: owner sign-off\n\n"
        "## queued\n"
        "- [W3] <script>alert(1)</script> queued slice · needs: W1\n\n"
        "## verified\n"
        "- [W4] gates green\n\n"
        "## done\n"
        "- [W5] already landed\n",
        encoding="utf-8",
    )
    reviews_dir = root / ".polyctl" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / "R-1700000000001.json").write_text(
        json.dumps({"id": "R-1700000000001", "slice": "W1", "state": "running", "submitted_at": time.time()}),
        encoding="utf-8",
    )
    claude_dir = root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    (claude_dir / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")

    view = start()
    status, headers, page = _request(view.port, "/pipeline")
    api_status, _, api_raw = _request(view.port, "/api/pipeline")
    data = json.loads(api_raw)

    assert status == 200 and api_status == 200
    assert headers["Content-Security-Policy"] == web.CSP
    assert list(data["columns"]) == ["waiting", "verified", "in review", "with a person", "landed"]
    assert [s["id"] for s in data["columns"]["waiting"]] == ["W3"]
    assert [s["id"] for s in data["columns"]["verified"]] == ["W4"]
    assert [s["id"] for s in data["columns"]["in review"]] == ["W1"]
    assert [s["id"] for s in data["columns"]["with a person"]] == ["W2"]
    assert [s["id"] for s in data["columns"]["landed"]] == ["W5"]
    assert data["columns"]["with a person"][0]["command"] == "polyctl slice start W2"
    assert any(item["kind"] == "harness-unseen" and item["command"] == "polyctl harness seen --by <your name> --ask"
               for item in data["person"])

    for col, sid in (("waiting", "W3"), ("verified", "W4"), ("in review", "W1"),
                     ("with a person", "W2"), ("landed", "W5")):
        section = re.search(rf'<section class="column" data-column="{re.escape(col)}">(.*?)</section>', page, re.S)
        assert section and f'data-slice="{sid}"' in section.group(1), (col, sid)
    assert "<code>polyctl slice start W2</code>" in page
    assert "<code>polyctl harness seen --by &lt;your name&gt; --ask</code>" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; queued slice" in page
    for forbidden in ("<script", "<form", "<button", "<input"):
        assert forbidden not in page.lower()


def test_serving_pages_and_api_endpoints_writes_nothing_to_the_project_or_home(start, project):
    Path(project["root"], project["mailbox"], URGENT).write_text("# stop W1\n\n## URGENT\n", encoding="utf-8")
    assert not os.path.exists(A.project_registry_path())
    assert not os.path.exists(os.path.join(project["root"], ".polyctl", A.PROJECT_KEY_FILE))
    before_project = _tree_digest(project["root"])
    before_home = _tree_digest(A.HOME)

    view = start()
    for path in ("/", "/board", "/pipeline", "/fleet",
                 "/api/status", "/api/board", "/api/pipeline", "/api/fleet"):
        status, _, _ = _request(view.port, path)
        assert status == 200, path

    assert _tree_digest(project["root"]) == before_project
    assert _tree_digest(A.HOME) == before_home
    assert not os.path.exists(A.project_registry_path())
    assert not os.path.exists(os.path.join(project["root"], ".polyctl", A.PROJECT_KEY_FILE))


def test_a_collected_review_leaves_in_review_and_a_verified_slice_waits_in_verified(start, project, monkeypatch):
    root = Path(project["root"])
    reviews_dir = root / ".polyctl" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_file = reviews_dir / "R-1700000000002.json"
    review_file.write_text(
        json.dumps({"id": "R-1700000000002", "slice": "W1", "state": "finished", "verdict": "NEEDS_CHANGES",
                    "submitted_at": 1700000000, "finished_at": 1700000004, "collected_at": 1700000005}),
        encoding="utf-8",
    )
    view = start()

    data = json.loads(_request(view.port, "/api/pipeline")[2])
    assert [s["id"] for s in data["columns"]["in review"]] == []
    assert [s["id"] for s in data["columns"]["waiting"]] == ["W1", "W2", "W3"]

    monkeypatch.setattr(
        A, "pipeline_items",
        lambda cfg: [A.next_item("implementer", "no-review", "no APPROVED review is bound to these bytes",
                                 "polyctl review", slice="W1")],
    )
    data = json.loads(_request(view.port, "/api/pipeline")[2])
    assert [s["id"] for s in data["columns"]["in review"]] == []
    assert [(s["id"], s["stage"]) for s in data["columns"]["verified"]] == [("W1", "no-review")]

    review_file.write_text(
        json.dumps({"id": "R-1700000000002", "slice": "W1", "state": "finished", "verdict": "APPROVED",
                    "submitted_at": 1700000000, "finished_at": 1700000004, "collected_at": 1700000005}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        A, "pipeline_items",
        lambda cfg: [A.next_item("implementer", "granted", "1 path(s) stand granted on G-1",
                                 'polyctl commit -m "<message>"', slice="W1")],
    )
    page = _request(view.port, "/pipeline")[2]
    data = json.loads(_request(view.port, "/api/pipeline")[2])
    assert [s["id"] for s in data["columns"]["in review"]] == []
    assert [(s["id"], s["stage"]) for s in data["columns"]["verified"]] == [("W1", "granted")]
    verified_col = re.search(r'<section class="column" data-column="verified">(.*?)</section>', page, re.S)
    assert verified_col and 'data-slice="W1"' in verified_col.group(1)


def test_a_type_error_inside_load_config_fails_closed_without_recording_the_project(start, project, monkeypatch):
    view = start()
    calls = []

    def broken_load_config(root, record=True):
        calls.append(record)
        if record:
            A.project_key(root)
        raise TypeError("malformed config value")

    monkeypatch.setattr(A, "load_config", broken_load_config)

    status, _, raw = _request(view.port, "/api/status")

    assert status == 500
    assert json.loads(raw) == {"schema_version": 1, "error": "TypeError: malformed config value"}
    assert calls == [False]
    assert not os.path.exists(A.project_registry_path())
    assert not os.path.exists(os.path.join(project["root"], ".polyctl", A.PROJECT_KEY_FILE))
