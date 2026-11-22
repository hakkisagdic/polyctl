# Pull requests

polyctl governs what lands in a checkout. What becomes of a branch once a person pushes it is GitHub's
to say: a check that failed there, a conflict with the base branch, a reviewer who asked for
changes. `polyctl pr watch --once` reads the open pull requests of this checkout's branches and mails
the implementer each such fact, once. With `pr.watch` on, a watchdog cycle runs that pass.

*In polyctl since slice PR-WATCH: `polyctl pr watch --once`, the `pr.watch` setting and `.polyctl/pr-watch.json`.
With `pr.watch` on, a watchdog cycle runs the same pass, so nobody has to start it (PR-WATCH-CYCLE).*

```bash
polyctl config set pr.watch on          # this project; off by default
polyctl config set pr.watch_minutes 30  # optional; 15 by default, and a value under 5 is refused
polyctl pr watch --once                 # one pass by hand: read, mail what is new, exit
```

## On a watchdog cycle

`pr.watch` is off by default, and a cycle with it off asks gh nothing and writes no
`.polyctl/pr-watch.last`. With it on, each live watchdog cycle runs the pass `polyctl pr watch --once`
runs. It reads at most once every `pr.watch_minutes` (15 by default; `polyctl config set` refuses a
value under 5). The time of the last attempt is `.polyctl/pr-watch.last` (one integer, and the file's
mtime), and the attempt is written after every read, including one that failed, so a gh that cannot
answer is not asked on every cycle. What was mailed stays in `.polyctl/pr-watch.json`, in the same
shape, one fact once per head.

A read that fails (gh missing, gh not authenticated, or gh failing) mails nothing and leaves
`.polyctl/pr-watch.json` untouched. It raises one alarm to a person, keyed `pr-watch-unreadable`, and
the alarm says what `polyctl pr watch --once` would have printed: `gh auth login`, or the places
polyctl looked for gh (PATH, `binaries.extra_dirs`, the usual install directories). The alarm stays
quiet for six hours. A later pass that reads says nothing more.

A dry cycle (`--dry-run`) asks gh nothing and writes no `.polyctl/pr-watch.last`. `polyctl pr watch --once`
remains one pass by hand, with the same exits.

## It reads, and never writes

polyctl asks gh two things, in the checkout and without a shell: `gh pr list` for the open pull
requests, and `gh pr view <n>` for each one that is this project's. It asks gh nothing that
writes - no comment, label, review, merge or push - so GitHub holds nothing polyctl put there. gh finds
the repository from the checkout's remotes, and polyctl finds gh as it finds any program: on PATH, in
`binaries.extra_dirs`, then in the usual install directories. gh gets no terminal to prompt on and
no colour, even from a shell that forces it with `CLICOLOR_FORCE` or `GH_FORCE_TTY`, so what it
answers is JSON. It is opt-in because it reaches GitHub on the project's behalf.

A pull request is this project's when its head branch is a branch of this checkout (`git branch`
lists it) in this repository, not in a fork. Every one is read before anything is decided, so a
pass that cannot read them all mails nothing and records nothing: a pull request left unread would
look as if its facts had cleared.

| when | exit | what polyctl prints |
|---|---|---|
| `pr.watch` is off | 2 | that it is off, and `polyctl config set pr.watch on` |
| `--once` is missing | 2 | that it runs one pass |
| gh is on no path polyctl searches | 1 | that gh is missing, and where polyctl looked |
| gh is not authenticated (its exit status 4) | 1 | `gh auth login` |
| gh fails, times out or answers with something that is not JSON | 1 | which read failed, and what gh said |
| another pass is running | 0 | that it stood down; it read and mailed nothing |
| a pass read everything | 0 | each mail it wrote, each fact already mailed, and the totals |

## Three facts

| fact | what GitHub says of the head commit | the mail points at |
|---|---|---|
| `check-failed` | a check's latest run ended FAILURE, TIMED_OUT, ACTION_REQUIRED or STARTUP_FAILURE, or its commit status is FAILURE or ERROR | `gh pr checks <n>`, and each failed check's link |
| `conflict` | `mergeable` is CONFLICTING | the base branch to bring into the head branch |
| `changes-requested` | the review decision is CHANGES_REQUESTED, or a reviewer's opinion asks for changes | `gh pr view <n> --comments`, and who asked |

GitHub keeps every run of a check, so a job re-run after it failed is listed beside the failure.
Only a check's latest run counts, the one that started last, as `gh pr checks` counts it: a check
run is one check by its name and workflow, a commit status by its context. gh also tells apart the
event that started a run, which `gh pr view` does not say, so two runs of one workflow started by
two events on one head - `push` and `pull_request` - are one check here, the later-started. A
failure that a re-run fixed is not mailed, and while a check that failed runs again its failure is
neither new nor cleared: what was mailed stands until the run ends.

A run still going, cancelled, skipped or neutral has not failed. STARTUP_FAILURE, a workflow that
could not start, has, although gh counts it as pending: nothing runs it again until somebody fixes
it. Whether GitHub requires the check makes no difference: a required check that failed ended as
any other did. While GitHub is still computing `mergeable` (UNKNOWN) the conflict is neither new
nor cleared, and what was mailed stands.

A reviewer's opinion is their latest review that approved, asked for changes or was dismissed. A
comment is no opinion, and a reply in a review thread is a comment, so a reviewer who asked for
changes and then answered a question still asks for them. Opinions are read beside the review
decision because a repository that requires no review has no decision to read.

## Once per fact

`.polyctl/pr-watch.json` records, for each pull request and fact, the head commit it was mailed at. A
fact is mailed when it stands on a head it was not mailed at, or when it was not standing at the
last pass: a push that leaves a check failing is mailed again, and so is a check that passes on a
re-run and then fails again; a fact that still stands on the same head is not. A fact that clears
is forgotten, and so is a pull request that is no longer open. A record polyctl cannot read is named,
and what stands is mailed once more.

A fact is recorded as soon as its mail is written, so a pass stopped part way - killed, or its
terminal closed - does not mail it again. One pass runs at a time: a pass that finds another one
running stands down, as a watchdog cycle does, because both would read one record and mail each
new fact twice.

## The mail

One mail per new fact, to whoever holds the implementer role, class `needs-read`, through the
writer every message polyctl writes takes: `agent-mail/<stamp>-pr-watch-to-<implementer>-PR-<n>-<fact>-<head>.md`,
with `pr`, `condition` and `head` in its envelope and a row in `.polyctl/ledger/mail.jsonl`. A name is a
message's id, so a fact that returns within the minute its first mail was written in gets a
numbered one. The mail names the pull request, its branches, the fact and what to look at. What
GitHub supplies - a title, a check's name, the link an integration gave a check - reaches it on one
line with every double hash broken, so a title reading `## URGENT` cannot make the mail urgent; a
review's own words stay on GitHub. The implementer fixes what the mail names as it fixes anything,
in a slice; pushing the fix stays a person's act.
