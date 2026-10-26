# Control surfaces

The agents run in terminals and IDEs. You are somewhere else — a desktop chat app, an
editor, your phone. Today that means walking over to look. It should not.

The fix is not a new app. It is **one event log with many cheap readers**.

## The event log

*In polyctl since slice EVENTS-LOG: polyctl appends one line to `~/.polyctl/events.jsonl` each time it records a
verification, submits a review or sees a submitted one end, grants commit authority, sends mail, and
nudges or wakes an agent; `polyctl events` reads the log, and with `--follow` prints each event as it is
written. Before, a surface learned what polyctl did by reading each project's files again, and a person
waiting on a submitted review ran `polyctl reviews` until it came back.*

```bash
polyctl events                                   # the newest 20 events of every project on this machine
polyctl events --project acme-api --since 2h     # one project's, of the last two hours
polyctl events --follow                          # then each event as it is written, until Ctrl+C
polyctl events --follow --json                   # each event as a line of JSON, for a program
```

Each line is one JSON object: when (`at`, seconds since the epoch, to the millisecond), which
project (`project`, the key its files in `~/.polyctl` carry), what happened (`kind`), and a short
payload (`data`) of ids, names and verdicts - never a body, a diff or a transcript. A field with
no value is left out.

```jsonc
// ~/.polyctl/events.jsonl
{"at":1790413391.207,"project":"acme-api","kind":"verification","data":{"id":"V-1790413391","passed":true,"profile":"quick"}}
{"at":1790413402.551,"project":"acme-api","kind":"review-submitted","data":{"review":"R-1790413402551","slice":"B8","tree":"4b825dc6…"}}
{"at":1790414318.004,"project":"acme-api","kind":"review-finished","data":{"review":"R-1790413402551","state":"finished","verdict":"APPROVED","slice":"B8","artefact":"2026-09-26-121838-a1b2c3d.md"}}
```

| `kind` | written when | `data` |
|---|---|---|
| `verification` | `polyctl verify` records its result | `id`, `passed`, `profile` |
| `review-submitted` | `polyctl review submit` pins the staged candidate | `review` (its `R-` id), `slice`, `tree` |
| `review-finished` | a submitted review ends | `review`, `state` (`finished`, `unavailable`, `failed` or `stale`), `verdict`, `slice`, `artefact` |
| `authority-granted` | `polyctl commit-ok` grants | `token`, `verification`, `review`, `waiver`, `index_tree` |
| `mail-sent` | polyctl writes a message into the mailbox | `message` (its file name), `kind`, `from`, `to` |
| `nudge` | the watchdog starts the implementer's turn | `pid`, `attempt`, and `exit` when the turn ended within its first seconds |
| `wake` | the watchdog wakes the architect | `why` (`reports` or `refill`), `pid`, `reports` or `queue`, and `retried` when a wake before it failed |

What the log leaves out is on the record elsewhere: a refused `polyctl commit-ok` stays in the authority
ledger, a review run in the foreground (`polyctl review` without `submit`) is seen by whoever runs it, a
submitted review whose run died before writing its end is the one `polyctl reviews` shows as lost, and a
message an agent writes into the mailbox by hand is not one polyctl sent.

The log observes; nothing reads it to decide anything. Writing an event never fails the command
that did the work: an event that cannot be written is said on standard error, and the
verification, grant or mail it would have told of stands. It is one file for the whole machine,
bounded as the other observation stores are: once it is a quarter past `retention.events_kb`
(2048 KB), its oldest lines go, back to three quarters of it. `polyctl events --follow` reads on across
that trim, and says so if a trim ever took lines it had not reached. Every string in a payload is
scanned for credentials first, as evidence is ([safety.md](safety.md)). `polyctl remove` leaves a
project's lines in the log: they are the machine's history.

```bash
polyctl config set retention.events_kb 4096 --machine
```

Not built yet: the other two producers. Hooks, where an agent's CLI has them - a `Stop` hook
with a `command` action appending a line, cheap and instant - and a poller, where it has none,
deriving a turn's end, its context and its cost from the records the vendor already writes. Until
then an agent's turns are read from its transcript, as `polyctl status` does.

Why this matters: without the log, every surface has to parse *N* vendor transcripts in
*N* formats. With it, a new surface is a file tail. That is the whole design.

## Surface 1 — terminal dashboard

The default. `polyctl watch` renders a panel from the project's files; leave it on a second
monitor, or keep it in a browser tab with `polyctl watch --web` (Surface 4). See the TUI section below.
`polyctl status` prints the panel once.

*In polyctl since slice LEADS-MCP: what the panel shows that an agent or a vendor wrote - what a session
says it does and its messages, mail's names and titles, the board's items, a returned review's
record, a project's name, keyflip's quota lines - is shown escaped, as `polyctl board`, `polyctl fleet`,
`polyctl tail`, `polyctl mail` and `polyctl agents` show it: a control character, a line feed among them, or a
direction override reads as `\x1b`, `\x0a` or `‮` and acts on nothing. An escape sequence in a
board title acted on the terminal of whoever watched, and a line feed in a name wrote a line that read
as polyctl's. A wrapped text is escaped a line at a time, and `polyctl tail` and `polyctl mail read` keep a message's
lines. A command the panel prints to copy, `polyctl review collect <id>` or `polyctl -C <path>`, holds its value
quoted as one word for the shell, and only a value no shell a person pastes it into reads as more: on
Windows the command may go into cmd.exe or PowerShell, so the value is always in double quotes, where
both read `&` and `|` as text, and since PowerShell runs `$(...)` inside them and cmd.exe expands
`%NAME%`, a value holding `$`, a backtick, `%`, `!`, a quote or a control character is shown and no
command is made of it. A tab is shown escaped too, where it moved what followed it to another column. A returned review's command is printed only for an
id polyctl makes (`R-` and digits); its record is a file in the tree, and one with another id is named as
none polyctl made. `polyctl status --json` prints the text as it is, for a program.*

*In polyctl since slice LEADS-OPEN: urgent banners before `polyctl lock` and `polyctl verify`,
commit refusal reasons, `polyctl reviews`, `polyctl decisions`, and `polyctl notices` also
escape terminal controls and direction overrides. List rows escape embedded
line breaks; a notice's detail body keeps its lines. Stored text and notice
JSON retain their original values. The broader `polyctl doctor` diagnostics are
not included in this sweep.*

*In polyctl since slice JSON-OUTPUT: `polyctl status --json` prints what the panel shows as one JSON document
and nothing else on stdout - no colour, no banner - for a program to read where it had to read the
panel. The panel is drawn from the same reading, so the two cannot disagree; `-m` and `--window`
shape both, and the exit status is the panel's. `polyctl fleet --json` ([parallel.md](parallel.md)) and
`polyctl notices --json` ([telemetry.md](telemetry.md)) do the same for theirs.*

| key | what it holds |
|---|---|
| `project`, `root`, `at` | the project's name, its directory, and when it was read, in epoch seconds |
| `implementer` | `adapter`; `state`: working, slowing, stopped, idle or unknown - unknown too where a fresh transcript needs the process table to tell working from stopped and the table cannot be read; `seconds_since_write`; `doing`, what its session says it does, or why the table could not be read; `session`, as polyctl resolved it: `id`, null where polyctl settled on none; `how`: pinned, recorded, discovered, ambiguous or unresolved; and `why`, what a person reads beside it, which a recorded or discovered session has too, so only a null `id` says polyctl could not resolve one; `working_elsewhere` (`name`, `root`, `seconds_since_write`) for the most recently written secondary transcript within the idle window, while the primary state is slowing, stopped or idle. Null with no implementer |
| `workspaces` | null while there is an implementer; without one, up to five workspaces with a local session to point polyctl at, newest first (`path`, `seconds_since_write`) |
| `telemetry` | `context_percent`, `cost_unit`, `turns`, `cost_total`, `cost_average`, `cost_delegated`, `last_turn_cost`, `last_turn_tool_calls`, and `machine_quota`: the lines keyflip reports for the other tools on this machine, never the implementer's own pool |
| `problems` | `nothing_to_do_since` (epoch seconds), `spinning_minutes`, `nudge_error` (`at`, `code`, `tail`, `log`) and `agent_errors` (`time`, `text`) |
| `returned_reviews` | reviews that ended and nobody collected: `id`, `slice`, `verdict`, `state` |
| `reviews`, `rounds` | the newest review artefacts (`file`, `verdict`); the rounds the running slice spent and its budget (`spent`, `budget`), null with no artefact |
| `throughput` | only passed, ready verifications count as staged; a waiting decision explains a stall only for the slice recorded by that verification (TRIAGE-1-MEDIUM). What the window produced: `hours`, `staged`, `landed`, `decisions_asked`, `decisions_open`, `oldest_open_minutes`, `state`, and `stall` (`minutes`, `candidate`, `paths`, `reason`) |
| `repository` | the newest three commits (`log`), `dirty_files`, and where the checkout stands: `ahead`, `behind`, `base`, `merged`; `ahead`, `behind` and `base` are null with no remote default branch to compare against |
| `mail` | the mailbox directory (`dir`), the messages in it (`waiting`), the marked ones for the role asking (`urgent`: `id`, `to`, `title`; null when the mailbox could not be read), and those nobody was shown, oldest first (`unseen`: `id`, `class`, `age_seconds`) |
| `board` | `counts` by state, and the `blocked` items: `id`, `title`, and `why`, null when the board gives no reason |
| `messages` | the recent messages, oldest first: `time` (HH:MM), `role` (user or assistant), `text` |

Without an implementer `telemetry`, `problems` and `throughput` are null and `messages` is empty.
Unlike the panel in a terminal, the document records no message as seen, whoever runs it: a program
reads it, and a status bar polling it would otherwise keep a marked message no person was shown from
climbing the watchdog's ladder ([messaging.md](messaging.md)). Such a message is in `urgent` and in
`unseen` both.

## Surface 1b — the one question: `polyctl next`

*In polyctl since slice NEXT.* `polyctl board` answers where an item is, `polyctl status` whether an agent is
alive, `polyctl gain` what the work cost. The question a person asks on coming back, and an agent asks
when its turn ends, is another one: which command, in what order, by whom. With eighty commands,
about fifty of them needing a project, that was answered from memory - and a landing chain stalls
in exactly that place: a candidate verified but never reviewed, a review approved but never granted,
a stand-in request left unread in `~/.polyctl/review-requests`, a harness route no person has accepted
holding every review that would follow it.

`polyctl next` reads those same stores through the readers the gate reads, and answers it. Every item
names its actor, and a person's item is shown as a command and run by no one: nothing here records,
grants or starts anything.

The chain is named at its first stage that does not hold, and it is `polyctl commit-ok`'s own reading of
the same candidate - the staged bytes, the newest verification bound to them, the review bound to
them or a person's waiver, the grant bound to them - so a candidate this calls ready is one the gate
agrees with. Where the two could drift, they are held against each other by a test that runs
`polyctl commit-ok` and requires it to refuse for the reason `polyctl next` named.

| form | what it prints |
|---|---|
| `polyctl next` | one block per actor, the command under the reason, then the line that says nothing here was run |
| `polyctl next --json` | `{"project", "person": [...], "implementer": [...]}`, each item `who`, `kind`, `why`, `command`, `detail`, `slice` - null where it has none |
| `polyctl next --short` | one line for a menu bar (how many actionable items wait for a person and how many for the implementer, with the command when one item is open), then `---` and the dropdown lines in the plugin output format SwiftBar and xbar read |

A stand-in review request that binds bytes no longer staged is listed as `review-superseded` with no
command, because `polyctl collect-review` refuses it and a person who typed the shown command would only
meet that refusal. A store that cannot be read is an item that says it cannot be read, never an
empty list, which would read as nothing waiting.

*In polyctl since slice SURFACES-SWIFTBAR: `polyctl next --short` and
`polyctl surfaces [install|uninstall] swiftbar --dir <dir>`. On macOS, SwiftBar and xbar read a plugin's
standard output as the menu-bar line before `---` and the dropdown lines after it, splitting each
line on `|` for item parameters (`bash=`, `shell=`, `href=`, `terminal=`). `polyctl next --short` prints
the summary line, `---`, and each actor's items as plain text with `|` escaped (`\x7c`) and no
parameter attached, so a person's step appears as the command text only and clicking a line never
runs a command. `polyctl surfaces install swiftbar --dir <dir>` writes one executable `polyctl.30s.sh` file in
the folder the person names (never a guessed folder), bound to the project's root and running
`polyctl next --short` and nothing else; it refuses to write over a file that is not polyctl's own byte-for-byte
plugin. `polyctl surfaces uninstall swiftbar --dir <dir>` removes only polyctl's `polyctl.30s.sh` file and leaves
every other file in that folder untouched.*

## Surface 2 — MCP, i.e. any chat app becomes the cockpit

This is the answer to *"manage it without leaving the app I'm already in."* Register the
server once in Claude Desktop, Cursor, Zed, VS Code — anything that speaks MCP:

```jsonc
{ "mcpServers": { "polyctl": { "command": "polyctl", "args": ["mcp", "serve"] } } }
```

Then the orchestration is reachable in ordinary conversation:

> *"What is Kiro doing?"* → `polyctl_status`
> *"What is blocked, and on what?"* → `polyctl_board`
> *"Has anyone answered its question?"* → `polyctl_decisions`
> *"Did the gates pass?"* → `polyctl_verify`, on a server started with `--allow-verify`
> *"Why has nobody nudged it in twenty minutes?"* → `polyctl_watchdog`

Not built yet: reading another agent's messages, writing to it and nudging it from the chat
app. Today they are `polyctl tail`, `polyctl note` and the watchdog.

No terminal, no context switch, no new UI to learn. The chat app you already have becomes
the control room, and the switches from [`mcp.md`](mcp.md) apply: `polyctl_verify` stays off
until you turn it on, and a server given no `--role` serves every tool, which is what a
person's own control room wants ([roles](mcp.md#roles)).

The MCP tools read the same files the CLI does, which is why a surface needs no store of its
own.

## Surface 3 — notifications

A `Stop` hook that fires a desktop notification costs one line and reaches you when you
are not looking at anything. Use `command`-type actions, never `agent`-type: an agent
action on turn-end can start another turn, and now you have a loop.

## Surface 4 — a browser tab

`polyctl watch --web` serves what `polyctl watch`, `polyctl board`, `polyctl next` (the pipeline) and `polyctl fleet` show
as four read-only pages (`/`, `/board`, `/pipeline`, `/fleet`) and four JSON endpoints
(`/api/status`, `/api/board`, `/api/pipeline`, `/api/fleet`) on 127.0.0.1, for a person who would
rather keep a browser tab open than a terminal:

```bash
polyctl watch --web                # http://127.0.0.1:8732/ is the panel; /board, /pipeline and /fleet sit beside it
polyctl watch --web --port 9000    # another port; 0 takes a free one, and the line it prints names it
polyctl watch --web --all          # the same pages; the address it prints is the fleet's
```

*In polyctl since slice WEB-VIEW: `polyctl watch --web [--port N]`. It is a view of polyctl, not a new app. Each
page is computed when it is asked for, from the project's own files, by the functions the three
commands print with: the view keeps no state, has no form, answers no method but GET (405 for any
other) and loads nothing from anywhere else - its style is inline, it runs no script, and its
Content-Security-Policy allows none. The reads it shares with those commands keep what they keep for
the next reader, such as a provider's quota reading; the view adds no write of its own. A page
refreshes itself every `--interval` seconds, 15 unless changed, with a meta tag. The server binds
127.0.0.1, refuses any address that is not loopback, and answers only a request addressed to
127.0.0.1 or localhost at its own port, so a page from another site cannot point its own name at this
machine and read the view through your browser. Loopback keeps the view off the network, not away
from the machine's other accounts: on a shared machine, anyone logged in can read it. One thing the
terminal does, a page does not: it marks no urgent message seen. Any process on the machine can
fetch a page, and a fetch is no proof that a person read it, so the message's alarm keeps climbing
until a command shows it to its reader. A page carries the panel's colours when polyctl's own output
would: started from a terminal, and not while `NO_COLOR` is set.*

*In polyctl since slice WEB-API: `/pipeline` renders each slice on the board into its pipeline column
(`waiting`, `verified`, `in review`, `with a person`, `landed`) on the server, with no script,
from the same readers `polyctl next` uses, and shows a person's step as the command text only; no page
or endpoint takes an action or writes anything to the project or `~/.polyctl`. Beside the four pages,
`GET /api/status`, `GET /api/board`, `GET /api/pipeline` and `GET /api/fleet` return the very data
the pages show, from the same functions (`status_facts`, `board_facts`, `pipeline_facts`,
`fleet_facts`), as JSON with a stable top-level shape and `"schema_version": 1`, under the same
`GET`-only (405 with `Allow: GET`), loopback-only and `Content-Security-Policy` rules.*

| endpoint | page | top-level keys |
|---|---|---|
| `GET /api/status` | `/` | `schema_version`, and the `status_facts` keys of `polyctl status --json` above |
| `GET /api/board` | `/board` | `schema_version`, `project`, `root`, `at`, `exists`, `problems`, `ready`, `sections`, `counts`, `mail` |
| `GET /api/pipeline` | `/pipeline` | `schema_version`, `project`, `root`, `at`, `columns` (`waiting`, `verified`, `in review`, `with a person`, `landed`), `slices`, `person`, `implementer` |
| `GET /api/fleet` | `/fleet` | `schema_version`, `at`, `projects` |

The menu-bar item (`polyctl surfaces install swiftbar --dir <dir>`, running `polyctl next --short`) is a reader
of the same kind: neither it nor the tab is the only way to do something.

## Align, don't depend

Borrowed, with credit, from keyflip's CodexBar bridge: **read what other tools leave on
disk; never require, spawn or link against them.** polyctl reads keyflip's
output if keyflip is installed and degrades quietly if it is not. The same courtesy is
owed to anything else on the machine.

`keyflip surfaces` already enumerates the AI tools present on a machine, and
`keyflip codexbar` reads CodexBar's config the same way. If those exist, use them; if not,
carry on.

---

# TUI: what we use and why

**Default renderer: Python standard library plus ANSI. No dependency, no install.**

Zero-install is the project's differentiator — an orchestrator you have to build before
you can watch your build is a bad joke. macOS and every Linux ship Python 3; ANSI works in
every terminal that matters.

That constraint is less limiting than it sounds. With stdlib alone the panel gets:

- the **alternate screen buffer**, so quitting leaves your scrollback intact
- **partial redraw** with cursor addressing instead of clear-and-reprint, which removes
  flicker entirely
- **resize handling** via `SIGWINCH`
- **single-key input** in raw mode: `q` quit, `r` refresh now, `m` read mail, `l` lanes,
  `1`–`9` switch project — no Enter, no prompt
- **sparklines** for credit burn and context growth, drawn with block characters
- **height-aware layout**, which is not a nicety: a panel taller than the window
  scrolls, and a scrolled panel stacks a fresh header on every refresh until the
  screen is nothing but headers. Lay out the fixed sections first, give the
  message log whatever lines remain, and truncate by real lines rather than by
  list elements — a section header carries its own leading blank line, so the two
  counts differ and off-by-two is enough to reintroduce the scroll.

That is a real TUI, in about two hundred lines, that runs anywhere.

Colour and screen codes go only where something draws them. Output that is not a terminal - a
pipe, a file, a scheduled job's log - carries no ANSI codes, and no output does while `NO_COLOR` is
set, to any value, or under `TERM=dumb`. There `polyctl watch` prints the panel once and exits: in a loop
it wrote the alternate screen and a clear before every frame into whatever read it, and never ended.

## Progressive enhancement, never a requirement

If `rich` or `textual` happens to be importable, the panel uses it for nicer tables and
truecolor. If not, the ANSI renderer runs. The feature set is identical; only the polish
differs. Nothing is gated behind an install. Not built yet: `polyctl watch` has only the ANSI
renderer today.

<!-- not built: polyctl watch has no --rich; the ANSI renderer is the only one -->
```bash
polyctl watch              # stdlib ANSI renderer
polyctl watch --rich       # uses rich/textual if present, otherwise falls back with a note
```

## What we rejected, and why

| Option | Why not |
|---|---|
| **Textual as the default** | Beautiful, and a `pip install` before you can see anything. It stays optional. |
| **Go / Rust TUI (Bubble Tea, ratatui)** | Single binary is genuinely attractive, but it adds cross-compilation, a release pipeline and a second language to a project whose core is a protocol and some scripts. Revisit if the panel becomes the main product. |
| **Web UI / Electron** | Heaviest possible answer to "show me six numbers", and it competes with Surface 2, which is better. `polyctl watch --web` is not one: it serves the panel's own text to a tab, with the standard library. |
| **curses** | In stdlib, but its model fights partial redraw and it degrades badly over SSH. Raw ANSI is simpler and more portable. |

The renderer is deliberately separated from the data layer, so replacing it later costs a
file, not a rewrite.
