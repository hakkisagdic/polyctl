# `polyctl archon` — Archon workflow bridge

`polyctl archon` is a standard-library CLI wrapper for bash nodes in Archon workflows. It talks
to Archon only by invoking the `archon` CLI on PATH and parsing its JSON output; polyctl never
imports Archon code and never assumes private paths or hosts.

## Contract

Every `polyctl archon` subcommand prints **one JSON line** to stdout and returns one of three
exit codes:

- `0`: completed (`{"ok": true, ...}`)
- `2`: usage error, invalid arguments, missing `archon` binary on PATH, or non-JSON `archon` output
- `3`: gate refusal (`{"ok": false, "refused": "<step>", ...}`), corrupt ledger on append, or leftover worktrees/branches

The `runs` and `leftovers` subcommands call `archon workflow status --json`, and `doctor` calls
`archon --version`. These invocations target the Archon v0.14.0 CLI shape and are exercised
against a fake `archon` binary in polyctl's test suite.

## Subcommands

### `polyctl archon doctor`

Checks whether `archon` is on PATH, reads its optional `--version` string, reports whether this
repository holds a valid `.polyctl/config.json` (`adopted`), and checks whether polyctl's
`pre-commit` hook is installed (`hooks_installed`). Never fails when `archon` is missing.

### `polyctl archon runs`

Runs `archon workflow status --json` and emits normalized rows `{run, workflow, state, branch}`:

```bash
polyctl archon runs
```

### `polyctl archon gate`

Runs polyctl's commit gate chain inside `--worktree <dir>` using `-C` root semantics: requires a
staged candidate, runs `polyctl verify`, verifies `--review <id>` when the profile demands a review,
grants authority via `polyctl commit-ok --verify`, and commits via `polyctl commit`. Never starts a
review actor, never waives, never pushes, and never writes to any other repository or worktree.

```bash
polyctl archon gate --worktree <dir> -m "feat: apply change" [--review <id>] [-p <profile>]
```

### `polyctl archon record`

Appends one hash-chained row to `.polyctl/ledger/archon.jsonl` under `polyctl-archon-row-v1`
([ledger](ledger.md#archon-runs)). Validates that `--sha` is 7–64 hexadecimal characters.

```bash
polyctl archon record --run <id> --event <event> --sha <sha> --undo <text> [--item <id>] [--result <text>]
```

### `polyctl archon notify`

Forwards an open question through polyctl's configured channels (Telegram, ntfy, e-mail) and
records a notice when `.polyctl/` is present. Never answers a pending decision.

```bash
polyctl archon notify --run <id> --text "Approve change?"
```

### `polyctl archon leftovers`

Inspects `--repo <dir>` against finished Archon runs from `archon workflow status --json` and
reports any matching linked worktrees or local branches that still exist (exit `3` if any, `0` if
none). Read-only: never deletes worktrees or branches and never signals processes.

```bash
polyctl archon leftovers --repo <dir>
```
