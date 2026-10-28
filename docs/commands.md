# Commands

Every `polyctl` command and what it does (`pctl` is the short command: the same parser, the same exit codes, the same `--version` line, and help and error messages that name the command you typed). The [README](../README.md) starts with the five you use for every change; [getting started](getting-started.md) is the first run, step by step.

| | |
|---|---|
| `polyctl status` · `polyctl watch` | one project: state, telemetry, problems, board |
| `polyctl watch --all` · `polyctl fleet` | every project, ordered by what needs a human first |
| `polyctl watch --web [--port N]` | the panel, the board, the pipeline and the fleet as read-only pages (`/`, `/board`, `/pipeline`, `/fleet`) and JSON endpoints (`/api/status`, `/api/board`, `/api/pipeline`, `/api/fleet`) on 127.0.0.1: a browser tab in place of a terminal ([surfaces.md](surfaces.md)) |
| `polyctl board` | where each item is; READY = queued items whose `needs:` are done |
| `polyctl next [--json\|--short]` | what stands in the way now, and whose hand closes it: a person's items first (a harness change nobody has read, a stand-in review request awaiting its answer, urgent mail, an open proposal), then the staged candidate's landing chain at the first stage that does not hold, each with the command that closes it; `--short` prints the menu-bar line, `---`, and the dropdown lines in the plugin format SwiftBar and xbar read. Read-only: nothing is run or recorded, and a person's command is shown, never typed ([surfaces.md](surfaces.md)) |
| `polyctl surfaces [install\|uninstall] swiftbar --dir <dir>` | write or remove polyctl's executable `polyctl.30s.sh` menu-bar plugin in the SwiftBar or xbar plugin folder you name (`--dir` is required; polyctl never guesses a folder), refusing to overwrite or remove a file that is not polyctl's own; the plugin runs `polyctl next --short` and nothing else ([surfaces.md](surfaces.md)) |
| `polyctl board add ID "title" --acceptance "…"` | admit one item, only with its acceptance boundary |
| `polyctl slice start <id>` · `polyctl slice block "…"` · `polyctl slice abandon --why "…"` | move a slice: start a queued one or resume a blocked one, park the running one with what it waits on, drop one on the record to `rejected`; each move is a line in `.polyctl/ledger/slices.jsonl`, and dropping one is the architect's or a person's ([slices.md](slices.md#commands)) |
| `polyctl slice status [<id>]` · `polyctl slices [--open]` | where a slice stands, since when and how it got there, its rounds and its newest review's findings; every slice on one line, a row moved or removed by hand named |
| `polyctl verify [-p full]` | run the declared gates, record the result |
| `polyctl commit-ok [--verify]` | may this tree be committed? decided from evidence |
| `polyctl commit -m …` · `polyctl commit-check --range A..B` | commit the granted candidate, its message ending with Polyctl- trailers that name the grant; check that each landed commit has the tree its trailers name, with no `.polyctl/` needed, as CI runs it ([gates.md](gates.md#a-commit-names-its-grant)) |
| `polyctl hold` / `polyctl hold release --note …` | stop every agent in the tree, and keep them stopped |
| `polyctl writers` / `polyctl writers --clean` | live turns in the tree (one per turn, not per process), orphans set aside; `--clean` stops only the orphans |
| `polyctl fanout ok --agents N` / `polyctl fanout record …` / `polyctl fanout history` | may a fan-out of N sub-agents start now (hard cap, recent limit hit, provider window); record what one cost |
| `polyctl gain [--since 7d] [--all] [--days 14] [--slices] [--json] [--sources] [--quota]` | one surface for what polyctl measured: landed slices and their outcomes, review verdicts, board depth, implementer spend and tool calls, watchdog wakes and refills, the last recorded run of each platform, and a daily spend/landed trend; every number is read from a ledger polyctl wrote, a store that cannot be read is named rather than shown as zero, and `--quota` asks the implementer's account only when named ([telemetry.md](telemetry.md)) |
| `polyctl evidence [record --platform windows --run ID]` / `polyctl evidence [show [--all] [--json]]` | a platform lane's CI run read through `gh` and recorded in the chained `.polyctl/ledger/platform-runs.jsonl`, and what each platform's newest run still vouches for: its status and conclusion, the commit it ran on, its jobs, and how far HEAD has moved since; a run not on this repository, not finished, not successful, not on a commit HEAD holds as an ancestor, or past `evidence.max_commits_behind` never reads as green and is a finding of `polyctl doctor --check`, and `polyctl gain` shows the same rows ([telemetry.md](telemetry.md)) |
| `polyctl cost --since 24h` | what the coordination itself spends: implementer turns by class (product / analysis / ceremony / coordination), wasted turns, reviews; `--since`, like every time a command takes, is `30m`, `2h`, `1d`, `today`, `yesterday` or a date; `--usd` prices the tokens in US dollars from a bundled price table, as an estimate ([telemetry.md](telemetry.md)) |
| `polyctl export otlp [--out <file>] [--attested]` | the project's ledger as OpenTelemetry traces in the OTLP/JSON encoding (one `ExportTraceServiceRequest`): one trace per slice (its candidate) and one span per gate step (`verification`, `review`, `grant`, `commit`) with hash-derived ids and the ledger's own times, written to `--out` or stdout; refuses a ledger this machine's checkpoint store does not cover unless `--attested` asks for only the attested rows (`polyctl.export.attested_only=true`); polyctl sends nothing anywhere ([telemetry.md](telemetry.md#otlpjson-trace-export-polyctl-export-otlp)) |
| `polyctl features [on|off <key>]` | the switches and what each costs; all off = deterministic polyctl, zero model spend ([features.md](features.md)) |
| `polyctl mode [show|lite|full]` | the project mode and what each mode does and does not protect: `lite` is the basic setup without enforcement (`enforcement: off - lite` on `polyctl status`, `polyctl doctor` and the MCP status, no reviewer probe, no commit hooks, `polyctl commit` refused), a person's act with `--by <name>` on the record; `full` checks an independent reviewer route and commit hooks and refuses naming what is missing ([configuration.md](configuration.md), [safety.md](safety.md)) |
| platforms | polyctl 0.7.0 is built and supported on macOS; Linux runs the test suite in CI but is not a supported platform yet; on Windows 29 tests fail (WINDOWS-LANE-0.7, docs/backlog.md) and Windows waits for a later release ([windows.md](windows.md)); the suite runs on Ubuntu for every push and pull request, on macOS weekly, and on Windows on demand until WINDOWS-LANE-0.7 |
| `polyctl waive review\|gates [--gates <names>] --slice B7 --by <name> --why …` / `polyctl catchup` | a person bypasses `review` or `gates` on the record (`inventory` is refused, since nothing in `polyctl commit-ok` reads an inventory waiver); a `gates` waiver stands in for the failed gates it names (all of the profile's when `--gates` is omitted) on one staged candidate whose verification ran every gate of the profile; catchup re-runs waived gates on the landed commit and closes the waiver when they pass, reviews each waived review's landed range with a model family other than the one that wrote it against what its commit messages claim, closes a `move-only` split on the proof its grant recorded, run again, and replays deferred wakes and nudges. `polyctl catchup --plan` previews it, names what closes by proof, and writes nothing, `polyctl catchup --limit 10` and `polyctl catchup --slice B7` bound a run, `polyctl catchup --author-family <family> --by <name>` is a person naming a family polyctl did not record, and `polyctl catchup --move-only <slices> --by <name>` is a person stating which waived slices only moved code, each closing only where the proof holds, and `polyctl catchup --slice B7 --reviewer <actor>` reviews with another reviewer actor of the table, so runs over different slices go side by side; a run exits 3 when the reviews it started decided nothing, 1 when a waived gate failed or a ledger could not be written, and 0 when it made progress or had nothing to do |
| `polyctl pings setup [--url-env NAME] [--all]` | dead man's switch: external pings that alarm when the watchdog and its doctor job both die; polyctl asks for the check's address and does not show it, a script names the variable that holds it, and `polyctl pings` shows where they go, never the whole address ([alarms.md](alarms.md)) |
| `polyctl hooks [status|install|uninstall] [--allow-shared-hooks]` / `polyctl push allow` | resolve Git's effective hook path; each role is independent, and shared/external/global mutations require explicit command-wide authorization |
| `polyctl skill install` / `polyctl skill show` | the playbook (roles, loop, authority, protocol, alarms, every command) rendered for the agents this repo uses: Claude skill, Kiro steering, AGENTS.md |
| `polyctl remove --yes [--allow-shared-hooks]` | two-phase removal: delete and commit `.polyctl-project` while enforcement remains active, then remove polyctl state after HEAD and index no longer contain it; foreign/protected hooks stay untouched. The second phase takes off the project's scheduled jobs and exactly its own files in `~/.polyctl`, lists each by name in the dry run, and exits 1 naming what it could not remove ([watchdog.md](watchdog.md)) |
| `polyctl update [--dry-run\|--yes]` | update polyctl the way it was installed: a git clone fast-forwards, and is refused while it has uncommitted changes; a Homebrew, pipx or uv install upgrades through its own tool, a pip install through the pip of the interpreter running polyctl. The command is shown first and runs on `--yes` or a yes at the terminal ([getting started](getting-started.md#5-update-and-uninstall)) |
| `polyctl uninstall [--yes] [--purge] [--allow-shared-hooks]` | take what polyctl installed off this machine: every scheduled job of polyctl's, polyctl's own hooks in each project the registry knows, and the `polyctl` entry in their MCP files; a dry run unless `--yes`, naming what it leaves - each project's `.polyctl/`, `~/.polyctl` unless `--purge`, and the program, with the command that removes it |
| `polyctl start [--yes]` | first-run wizard from nothing to a working, governed project: detects installed agent CLIs and their model families, proposes a cross-family implementer/reviewer pair that polyctl's independence rule accepts (measured `verified` levels first, saying why each pair is offered), writes the choice as a profile, asks before running `polyctl demo`, `polyctl init`, `polyctl hooks install` and `polyctl prove` (`--yes` runs only the steps that need no person), and ends by listing the steps only a person can take (`polyctl harness seen --ask`); never records a person's approval or installs software ([getting started](getting-started.md)) |
| `polyctl init --profile agy-codex|codex-agy|claude-codex [--review-tier same-family|person] [--language en|tr]` | write role blocks and exact `.polyctl-project` enrollment marker without staging it; a single-harness setup chooses a review tier ([profiles.md](profiles.md)); `--language tr` has what polyctl writes into the project and for its people in Turkish ([configuration.md](configuration.md)) |
| `polyctl demo [--keep]` | the guarantee in about a minute, before polyctl is on a repository of yours: on a scratch project with a home of its own and a stand-in reviewer, a change with a bug is refused by review, `polyctl commit-ok` and the commit hook, and its fix lands with its Polyctl- trailers; nothing outside the scratch folder is touched, and `--keep` keeps that folder ([demo.md](demo.md)) |
| `polyctl doctor --check` | quiet doctor for a scheduler: one line per problem, exit 1, alarms raised — installed as a 15-minute launchd job, or systemd user timer on Linux, by `polyctl watchdog install` |
| `polyctl email setup` / `polyctl email test` | the red alarm channel: e-mail via formsubmit.co, no server ([alarms.md](alarms.md)) |
| `polyctl alarms` / `polyctl alarms test --level red` | live alarm episodes and their level; test rings every channel |
| `polyctl mail log` / `polyctl mail search <text>` / `polyctl mail ack <glob>` | the mail ledger: every message written and when it was consumed, searchable after deletion |
| `polyctl watchdog explain` / `polyctl watchdog trace` | why the watchdog did or did not act: measurements and verdicts of this cycle, and of the recorded ones ([watchdog.md](watchdog.md)) |
| `polyctl source import` | admit tracker items onto the board |
| `polyctl mail` · `polyctl notices` | coordination messages; alerts this project raised |
| `polyctl watchdog install` | launchd job, or systemd user timer on Linux, that restarts a stalled agent ([watchdog.md](watchdog.md)) |
| `polyctl mcp serve [--project all]` · `polyctl a2a serve` | expose state, read-only resources and prompts to MCP clients (`--project all` serves every registered project) / as A2A tasks |
| `polyctl telegram setup` | alerts to your phone, decisions back from it; polyctl asks for the bot token and does not show it, finds the chats that wrote to the bot, and writes `~/.polyctl/telegram.json` itself ([telegram.md](telegram.md)) |
| `polyctl ntfy setup --topic-url <url> [--token-env NAME]` / `polyctl ntfy test` / `polyctl ntfy status` | outbound phone alerts via ntfy.sh or your own ntfy server; writes `~/.polyctl/ntfy.json` mode 0600, reads an access token only from `$NAME` (never an argument, never printed, never logged), and sends each alert with a priority from its alarm level ([alarms.md](alarms.md)) |
| `polyctl digest [--days N]` | what happened, read from the ledgers — also answers "why is nothing moving" |
| `polyctl ask` · `polyctl answer` · `polyctl decisions` | questions answerable in one tap; free text always last; an answer must be an offered key, and `polyctl answer <D-id> <key> --change` replaces one while the first stays on the record |
| `polyctl propose "…" --why "…" [--rule-file <path>]` · `polyctl proposals` | an agent proposes a change to a rule it works under instead of editing it: recorded in the decision ledger with its evidence, and a person accepts or rejects it with `polyctl answer`; nothing writes the rule file ([protocol.md](protocol.md#changing-the-rules-an-agent-proposes-a-person-decides)) |
| `polyctl note` | an architect message into the mailbox, through the tool |
| `polyctl review` | review the tree with an actor that did not write it |
| `polyctl person-review --by <name>` | a person reads the staged diff, then records `--verdict APPROVED` or `NEEDS_CHANGES` with the `--digest` it showed; bound to the candidate like any review, labeled `person review`, never an agent's command |
| `polyctl harness seen --by <name>` | a person reads each change an agent made to what a harness reads here - hooks, plugins, MCP servers, instructions - and to the command a role's turn, a review or a hunt starts with, then records them with the `--digest` it showed, or in one step at a terminal with `--ask`, as for their own tool approvals; until then no wake, refill, nudge, hunt or lane starts in the tree, what `polyctl init` and `polyctl skill install` write of their own is seen already, and it is never an agent's command ([safety.md](safety.md#harness-configuration-an-agent-changed-waits-for-a-person)) |
| `polyctl review --commits <range>` | review landed work after the fact; exit 3 means no reviewer could review (never a verdict), fallbacks in `reviewer.fallbacks` ([roles.md](roles.md)) |
| `polyctl review --commits <range> --reviewer <actor> --slice <id>` | review a landed range again with another reviewer actor of the project's table, recorded as the slice that landed it and judged against its commit messages ([roles.md](roles.md)) |
| `polyctl ci review --base <rev> --reviewer <adapter> --model <model> --family <family> --author-family <family>` | a pull request's change reviewed in CI by a model of another family, with no setup: the commits `--head` adds to the merge base, held to the family the workflow states wrote them, with the verdict and the findings appended to `--summary` and `--outputs`; it grants nothing. The repository's `action.yml` runs it ([github-action.md](github-action.md)) |
| `polyctl handoff` | write and send everything a successor needs |
| `polyctl a2a-mcp serve` | reach A2A agents from an MCP-only client; a header in `.polyctl/a2a-agents.json` names the variable that holds its value, `${NAME}`, so the project holds no secret ([mcp.md](mcp.md)) |
| `polyctl prune` | trim accumulated records and logs |
| `polyctl doctor` · `polyctl adapters` | check the wiring; what is supported and how well |
| `polyctl completion zsh` | print a script that completes polyctl's commands, options and choices; `bash`, `fish` and `powershell` too, installed as [getting started](getting-started.md#6-shell-completion) shows, and printed again after `polyctl update` |
| `polyctl --version` | the installed version |

Hook status separates static intent from executable enforcement. polyctl enforcement is
opted in only by a root `.polyctl-project` whose exact `polyctl-project-v1\n` bytes exist in
HEAD or the active index; an incidental `.polyctl/` directory is inert. A staged marker
enables first adoption, while a staged deletion remains enrolled through HEAD until
that deletion is committed. An enrolled project requires `.polyctl/config.json` to be a
valid, non-empty top-level JSON object. polyctl reads at most 1,048,576 bytes and
rejects container nesting deeper than 64 before recursive JSON decoding;
pre-dispatch loading and commit enforcement use the same bounded result. Missing
or unreadable state refuses with the one-line `polyctl init --profile agy-codex`
repair.

The `current-local (behavior unverified)` and `current-scoped (behavior unverified)`
labels describe bytes only; `pre-commit execution: installed (execution proved)`
is printed only after Git resolves and runs the active hook with an isolated
synthetic index and polyctl returns the nonce-bound refusal for that exact challenge.
The probe never commits, changes the real index, or writes a Git object. Git may take
`hooks.probe_timeout_seconds` (60 by default, a machine setting) to run the hook; on a
machine busy enough the 15 seconds it was given were not enough, and an installed hook
was reported unproven (HOOK-PROBE-TIME). A missing,
misplaced, non-executable, stale, foreign, or fail-open hook is `not installed`, and
`hooks status`, `doctor`, `doctor --check`, and `init` consume the same result.
`status` also names the effective path, path class, winning `core.hooksPath`
scope/origin/value, track state, and misplaced polyctl forms. A hook installed in the
repository's git directory also names the polyctl that installed it, and falls back on that
file only when `/bin/sh` finds no polyctl on PATH; `hooks status` and `doctor` say when it
cannot, with the symlink that fixes it. Install handles
pre-commit and pre-push independently, so it may install an eligible pre-commit,
preserve a custom pre-push byte-for-byte, report the push-window hook unavailable,
and return 1. Install, uninstall, and remove refuse the entire mutation set when
any eligible target is shared, external, or selected by global/system config
unless `--allow-shared-hooks` is explicit.


## Tests

The hosted `tests` workflow runs the suite on every push to main and every pull request
on Ubuntu, with Python 3.9 (the support floor) and 3.12, and on macOS every week on
Python 3.12; Windows runs on demand until WINDOWS-LANE-0.7 (`gh workflow run tests -f
os=windows-latest -f python=3.12`, and `-f utf8=off` without Python's UTF-8 mode, as a
default install runs it; [windows.md](windows.md)). The
repository is public, so the hosted runners cost nothing, and the pre-push hook still
runs the suite locally before a push: first the tests the pushed commits touch, then the
whole suite, in four processes where pytest-xdist (the `dev` extra) is installed -
`POLYCTL_PREPUSH_WORKERS` sets how many, and 0 keeps one. A release tag runs the suite again
before it publishes. Hosted runs cover OS
API behavior and deterministic process crashes with real child processes and
temporary paths. They are not physical power-loss, storage-controller or filesystem
qualification, including unsupported and network filesystems.
