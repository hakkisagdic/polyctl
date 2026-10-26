# Reference scripts

The observation layer, working today. Standard library Python only — no install,
no dependencies, in keeping with `docs/surfaces.md`.

```bash
bin/polyctl projects        # workspaces with a local agent session
bin/polyctl status          # one-shot summary
bin/polyctl watch           # live panel; leave it in a background terminal
bin/polyctl tail -n 5       # recent messages from the implementer's transcript
bin/polyctl mail list|read|send
bin/polyctl adapters        # registry and verification status
bin/polyctl verify          # run the declared gates yourself and record the numbers
bin/polyctl doctor          # check this workspace's wiring

scripts/polyctl-watchdog --root ~/work/project   # restart a stalled agent, cheaply
```

Run them from inside the project you are orchestrating, or point at one from
anywhere with `-C`:

```bash
bin/polyctl -C ~/work/acme-api watch
```

Run from a directory with no project, `polyctl` says so and lists the workspaces it
can see rather than rendering an empty panel. With no configuration at
all, `polyctl` discovers the implementer session by scanning local agent stores for one
whose workspace matches the current repository — so `bin/polyctl status` works on the
first try.

## Configuration (optional)

`.polyctl/config.json` in the project root. The documentation shows YAML for
readability; these scripts read JSON so they stay dependency-free.

```json
{
  "project": "acme-api",
  "implementer": { "adapter": "kiro", "session": "sess_…", "workspace_hash": "…" },
  "mailbox": "agent-mail",
  "reviews": "semantic-review",
  "round_budget": 5
}
```

## What they will not do

Observation is strictly read-only: nothing here writes to a vendor's session
store, and nothing drives an agent. `resume`, `verify`, `commit-ok`, `slice`,
`decide`, `since` and `mcp serve` are specified in `docs/` and not implemented —
the commands say so rather than pretending.

## The watchdog

Turn-based agents stop when a turn ends, mid-slice or not, and then wait. The
watchdog notices and nudges — but detection is free and only the nudge costs
anything, so it refuses to spend when spending would not help:

| Guard | Behaviour |
|---|---|
| Session still writing | do nothing |
| No open work (clean tree, no mail, last review approved) | do nothing |
| Slice over its round budget | notify a human; never nudge into the same round again |
| …unless the architect re-specified since the last review | proceed |
| Provider out of headroom (keyflip) | notify, do not nudge |
| Two or three nudges produced no transcript growth | back off, then hand over to a human |

Install it as a launchd job so it survives your terminal, your orchestrator
session and a reboot:

```bash
polyctl -C ~/work/project watchdog install     # every 120s, nudge after 6m idle
polyctl -C ~/work/project watchdog status      # is it loaded? recent log lines
polyctl -C ~/work/project watchdog uninstall
```

Run it by hand, or every couple of minutes from launchd/cron. Idle threshold
defaults to six minutes; `--dry-run` prints the decision without acting.

## Keeping work moving without you

A blocked slice must not stop the run: the architect can hit a quota limit and the
human can be away. Two pieces make that safe.

**A pre-authorised backlog** (`.polyctl/backlog.md`) lists work whose acceptance
boundary was written in advance. When the implementer hits something needing an
architectural decision, it parks that slice, leaves a `DECISION REQUIRED` message and
takes the next backlog item — using authority that already exists rather than
inventing any. The watchdog's default prompt carries this rule.

**Declared gates** (`.polyctl/gates.json`) let `polyctl verify` execute the checks itself
and write the numbers to `.polyctl/ledger/verifications.jsonl`. Commit authority is
granted against that record rather than against the implementer's report, so the
gate does not depend on a human being awake — while push, PR and marking work
complete stay human-only, permanently.
