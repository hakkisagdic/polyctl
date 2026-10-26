# Model and effort control

Model choice and reasoning effort are the two biggest levers on both cost and quality,
and they should be a property of **the slice**, not a setting you forget you changed.

## Commands

Today a model and an effort are chosen for a role when it is assigned
([`profiles.md`](profiles.md)):

```bash
polyctl init --implementer kiro --model <model> --effort high   # written to .polyctl/config.json
polyctl role set reviewer claude-code --model <model>           # the reviewer, composed from its adapter
```

An effort the adapter does not list in its `effort_values` is refused for a reviewer and left
out of the implementer's nudge, with a note.

Not built yet: reading or changing them while a project runs, and a one-turn override.

<!-- not built: polyctl has no model, effort or run command -->
```bash
polyctl model                          # what the implementer is running now
polyctl model list                     # models the adapter's CLI reports
polyctl model set gpt-5.6-sol          # for subsequent turns
polyctl effort set max                 # low | medium | high | xhigh | max (adapter-clamped)

polyctl run --model <m> --effort <e> "<prompt>"   # one turn only, no persistent change
```

In the design, values are clamped to the adapter's `effort_values`, so a profile written
for a CLI with five levels still works against one that has three.

## Per-slice policy

Not built yet: a policy file mapping slice kinds to a model and effort, so routine work stops
burning the expensive configuration. polyctl reads no such file; a model and an effort are chosen
per role.

<!-- not built: polyctl reads no policy file; a model and an effort are chosen per role -->
```yaml
# .polyctl/policy.yml
default:        { model: gpt-5.6-sol,  effort: high }
architecture:   { model: gpt-5.6-sol,  effort: max }     # contracts, security boundaries
implementation: { model: gpt-5.6-sol,  effort: high }
mechanical:     { model: gpt-5.6-luna, effort: low }     # exports, renames, formatting
verification:   { model: claude-opus-5, effort: high }   # a second opinion from another family
```

`mechanical` matters more than it looks. In a real run, an entire review cycle was spent
on one missing export from a barrel file — a task that does not need a frontier model at
maximum effort.

The `verification` row is deliberate: reviewing with a **different model family** than
the one that wrote the code catches failure modes a self-review shares and misses.

## Which CLIs expose what

| CLI | Model flag | Effort flag |
|---|---|---|
| Kiro CLI | `--model` | `--effort` (low…max) |
| Claude Code | `--model` | — |
| Antigravity | `--model` | `--effort` (low…max) |
| Codex | `--model` | `-c model_reasoning_effort=` |
| Aider | `--model` | `--reasoning-effort`, `--thinking-tokens` |
| opencode | `--model provider/model` | — |
| Gemini / Cursor / Copilot / Q | `--model` | — |
| Amp | — (chosen internally) | — |

Where a CLI has no effort flag, the adapter sets `effort: null` and `polyctl` reports that the
lever is unavailable rather than silently ignoring your setting.

## Cost awareness

polyctl does not do cost accounting — that is
[keyflip's](keyflip.md) job. What it does is make the *decision* explicit and reviewable:
each role's model and effort are written into `.polyctl/config.json`, in the repository, so "why
is this slice running at max effort" has an answer in version control.
