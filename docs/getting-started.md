# Getting started

From an empty checkout to a working, governed project. Start with `polyctl start`, the first-run
wizard, or run each step it walks you through (`polyctl demo`, `polyctl init`, `polyctl hooks install`,
`polyctl prove`) by hand. A test runs this sequence in a temporary repository, so this page cannot
drift from what polyctl does.

```bash
pip install polyctl
cd your-repository
polyctl start                             # asks before each step; --yes runs the steps that need no person
```

`polyctl start` walks from nothing to a proven project:

1. **Detects the agent CLIs installed** on this machine (from the adapters polyctl ships, as
   `polyctl adapters` reads them) and their model families.
2. **Proposes a cross-family implementer/reviewer pair** that polyctl's independence rule accepts,
   preferring adapters with a measured `verified` level (`full`, then `partial`, ahead of
   `documented` or `untested`) and saying why each pair is offered (their model families,
   their `verified` levels, and the reviewer's read-only flag).
3. **Writes the choice as a profile** in `~/.polyctl/adapters/profiles.json`, as `profiles.json`
   and `polyctl init --profile` already know.
4. **Runs `polyctl demo`, `polyctl init`, `polyctl hooks install` and `polyctl prove`**, asking before each step
   (or, with `polyctl start --yes`, running the steps that need no person without prompting).
5. **Ends by listing the steps only a person can take** — such as `polyctl harness seen --ask`,
   wiring your own rule file, and landing the initial `.polyctl-project` and `.polyctl/` setup through
   the governed loop. `polyctl start` never records a person's approval itself and never installs
   software.

The sections below show what each step does when you run it directly.

## 1. Install and put polyctl on the repository

```bash
pip install polyctl
cd your-repository
polyctl start                             # or run polyctl init directly:
polyctl init --profile agy-codex          # or codex-agy, claude-codex
```

`polyctl init` writes `.polyctl/` (config, gates, board), the mailbox, the playbook and the MCP
registration, and the `.polyctl-project` marker, which you commit: it is what turns enforcement on.
It refuses when no reviewer answers, when the reviewer is of the implementer's own model family,
or when the quick gates exercise none of your code. Its authority, board, backlog and mailbox
files are in English, and so is what polyctl tells you afterwards - the digest, the handoff, alarms and
the phone; `polyctl init --language tr` has them in Turkish ([configuration](configuration.md)).

*In polyctl since slice LEADS-ADAPTERS: `polyctl init` writes in the project alone, and keeps files already there.*
Each file it makes - the marker, the first configuration, the board, backlog, authority and gates of
`.polyctl`, the mailbox's README, a harness's coordination - is made exclusively: a file, folder or link
that appears before the open is kept. In a project whose state already exists, `polyctl init` keeps every
file and role block it finds - `.polyctl/config.json`, `.polyctl/gates.json`, `.polyctl/board.md`, `.polyctl/backlog.md`,
`.polyctl/authority.md` and `.polyctl/ledger/*.jsonl` - adds any role blocks (`implementer`, `reviewer`,
`architect`) a profile or flag names that `.polyctl/config.json` lacks, and
writes only what is missing (the playbook, the skill, the steering and `.polyctl/init-manifest.json`),
saying which files and role blocks it kept and which it added (INIT-OWN-PRE-PUSH, INIT-OWN-PRE-PUSH-2). A configuration that appears after init
planned without one is named, and init exits 1 before writing the rest; run init again to plan from it.
Existing configuration changes (`--language`, `--review-tier same-family`, missing role blocks) and a missing manifest are
written whole. On POSIX a link at the manifest's name is replaced without following it; Windows refuses
it. The same tree primitives write `.polyctl/project-key`; if that write is refused, the machine's
registry keeps the name.

What init adds to - the playbook, a rule file with `--rules`, an MCP registration - is read and replaced
whole through no link. A rule link such as `CLAUDE.md -> AGENTS.md` is named and accepted when it resolves
inside the project to another rule file this run writes successfully: the pointer is written once,
through the target's own path. A link outside the project or to a file this run does not write is refused.
Other links where polyctl adds text are named, left alone, and init exits 1 having written the rest.

On macOS and Linux each folder is opened from the project's root down, relative to the one before it
with `O_NOFOLLOW`; the leaf is opened relative to the held folder. On Windows native handles hold every
folder without delete sharing until the file operation ends, so no folder can be renamed or replaced
meanwhile; reparse points, including links and junctions, are refused ([windows](windows.md)).
A platform offering neither safe way refuses the operation. The opt-in ledger used by
`--review-tier same-family`, its lock and its seal use the same held folders, preserving the chain and
machine checkpoint. Known JSON MCP formats are merged by polyctl itself; for another format polyctl refuses to
run a vendor command that could be redirected, names the command for you to run, and exits 1.
Init appends only to a `.gitignore` that is a regular file with one name, opened through no link;
otherwise it names the lines for you to add. `polyctl skill install` writes the playbook as init does,
and exits 1 when it did not write one.

With one harness for both roles, a same-family reviewer is refused until you choose a
[review tier](roles.md#review-tiers) for `full` mode: another model of the same family, labeled as weaker
independence wherever its reviews show, or no model reviewer at all and a person reviewing each
candidate.

```bash
polyctl init --implementer claude-code --review-tier same-family --by <name>
polyctl init --implementer claude-code --review-tier person
```

Where `polyctl init` would refuse a `full` setup because no independent reviewer is available
(for example, the reviewer binary is missing or a same-family reviewer was given no `--review-tier`) or
because the `pre-commit` commit hook cannot be installed or kept current (a redirected repository, an
unknown enrollment, a hook path that is not a directory, a foreign or tracked non-polyctl `pre-commit`
hook, or a shared hooks path on Windows), it refuses with nothing written and says how a person can start
in `lite` mode instead: `polyctl mode lite --by <name>`, then `polyctl init` (for a shared hooks path
elsewhere, `polyctl init` succeeds and names `polyctl hooks install --allow-shared-hooks` as the next
step). The commit gate is the `pre-commit` hook: a `pre-push` hook the repository keeps - one polyctl did not
install, tracked in the tree `core.hooksPath` names or present before polyctl's enrollment and never
replaced by polyctl - is left byte for byte by `polyctl init` and `polyctl mode full`, `polyctl init` reports in
one line that the push guard is off (why it is not installed here and what installing it would take), and
`polyctl status` and `polyctl doctor` show the push guard as off rather than an error; a `pre-push` where
polyctl's own stood is warned about as a changed guard, and if `polyctl mode full` cannot install an
eligible `pre-push` it says that `pre-push` was not installed and why (INIT-OWN-PRE-PUSH, INIT-OWN-PRE-PUSH-2).
`lite` is the basic setup without enforcement: no reviewer probe and no commit hooks, `polyctl commit`
refuses because there is no gate to commit through, and every surface that reads the mode
(`polyctl status`, `polyctl doctor`, the MCP status) says plainly `enforcement: off - lite` that nothing
is enforced ([safety](safety.md)). Once an independent reviewer route and hooks are ready, switch the
project to `full` mode:

```bash
polyctl mode show                         # the current mode and what each mode does and does not protect
polyctl mode full                         # checks reviewer independence and hooks, refuses if anything is missing
polyctl mode lite --by <name>             # a person switches the project to lite, on the record
```

## 2. Wire what makes the guarantees hold

```bash
git add .polyctl-project .gitignore && git commit -m "adopt polyctl"
polyctl hooks install                     # the pre-commit hook that refuses unauthorised commits
```

The marker goes first. Until `.polyctl-project` is tracked the current hook stands aside, so
`polyctl hooks install` refuses a project whose `.polyctl/config.json` already governs its commits: put in
place before the marker, the hook would switch that authority off.

The reviewer is another model family than the implementer's, another model of its family where
a person opted in, or a person with `polyctl person-review --by <name>`; a reviewer that is the same
actor, or of no [review tier](roles.md#review-tiers), is refused.

### A project an older polyctl set up

A project set up before `.polyctl-project` existed has everything but the marker: `.polyctl/` with its
config, board, ledgers and decisions, a commit hook that runs `polyctl commit-check`, and no
`.polyctl-project` anywhere in its history. Its config governs its commits, `polyctl hooks install`
refuses it for the reason above, and `polyctl doctor` names the one command that adopts it:

```bash
polyctl init --adopt
```

It writes the exact marker if the working tree has none and stages it, so the project is
enrolled from that moment. It then installs the current hooks the way `polyctl hooks install` does,
has Git run the commit hook to prove that it refuses, and says what it wrote, what it kept and
what is left to commit: the staged `.polyctl-project`, landed through `polyctl verify`, `polyctl review`,
`polyctl commit-ok` and `polyctl commit`. Keep it staged until then; the current hook enforces while the
marker is in the index or in HEAD. Where Git runs this repository's hooks from a shared or
external place, as it does for linked worktrees, `polyctl init --adopt --allow-shared-hooks`
authorizes the install.

*In polyctl since slice INIT-ADOPTION: `polyctl init --adopt` enrolls polyctl state that no tracked
`.polyctl-project` covers - a project an older polyctl set up, or one whose marker `polyctl init` wrote and
nobody staged - in one step, where the commit hook's refusal, `polyctl hooks install` and `polyctl doctor`
each spelled out a recipe of their own. Adoption writes nothing under `.polyctl/`, so every ledger and
decision stays as it was; a `.polyctl-project` that is not exactly `polyctl-project-v1` is refused, never
replaced, and a staged marker that does not read back as one is unstaged again, which leaves the
project governed as it was. Run again, it leaves the marker where it is and only makes sure of the
hooks. It exits 0 only when Git was seen to run the commit hook. The options of a new setup, such
as `--profile`, are refused beside it; `polyctl doctor`, `polyctl doctor --check`, `polyctl prove`, the commit
hook's refusal and `polyctl hooks install` name it wherever they meet such a project.*

*In polyctl since slice TRIAGE-HIGHS: such a project whose `.polyctl/config.json` cannot be read is refused
by `polyctl hooks install` too: its old hook refuses every commit, and the current one would have let
each through. `polyctl hooks install`, `polyctl doctor` and `polyctl prove` name what cannot be read, to make
readable first, and then `polyctl init --adopt`, which refuses the project until then.*

## 3. Prove it

```bash
polyctl prove
```

Three checks, each run, not described:

- **the hook refuses an unauthorised commit** — Git runs the active pre-commit hook against
  a synthetic candidate and it must refuse;
- **the reviewer answers and is another actor** — it must echo a nonce, and a review tier must
  admit it; a same-family reviewer is proven and labeled, and a project reviewed only by a person
  has no reviewer to prove;
- **a throwaway slice lands end to end** — a one-line change in a temporary worktree goes
  through `polyctl verify`, `polyctl review` and `polyctl commit-ok`. Nothing is committed, the worktree is
  removed, and its review is kept under `~/.polyctl/archive/<project>/`.

Each check that fails says what would fix it. `polyctl init --prove` runs the same checks as its
last step. The throwaway review spends one short review from the reviewer's quota;
`--no-review` skips it and says that slice is not proven.

*In polyctl since slice LEADS-INSTALL: each run keeps its review in an archive of its own,
`prove-<time>`, then `-2` and on for another run in the same second, which was merged into the
first; an archive that cannot be written is said, and the worktree is removed all the same, where
it stayed registered in the checkout. The throwaway borrows the untracked dependency directories
`merge.link_paths` names (`.venv` and `node_modules` unless set) from this checkout, as
`polyctl merge-check` does, so that its gates can run: a gate that writes into one - an install, a
cache - writes into this checkout's.*

## 4. The first slice

Put it on the board with the boundary it will be judged against, then the loop the playbook
describes:

```bash
polyctl board add FIRST "what the slice does" --acceptance "what it must meet; the suite passes"
polyctl board ready                       # what may start now
polyctl slice start FIRST                 # it runs, and the move is recorded
# work, then stage exactly the candidate
polyctl verify -p quick
polyctl review
polyctl commit-ok
polyctl commit -m "…"
```

An id is what the board carries whole between a line's brackets and what another item's `needs`
can name: no space, comma, `]`, backslash or `·`, and no `(` or `/` first. A phase of a plan, such
as `ACME-187/1`, is baselined on `.polyctl/plans/ACME-187.md` as it stood when the item was admitted, so
a later edit of the plan shows as drift. `--needs A,B` is read the way the board reads a needs note,
and `--role` names the role that takes the item when that is not the implementer.

*In polyctl since slice BOARD-ADD-2: ids such as `ACME-187/1` are admitted, and `--needs` is checked as
the board will read it; before, the first were refused as ids no line could carry, and a dependency
could pass the check and be written as two ids the board did not hold.*

No push: that stays a person's act. `polyctl doctor` shows the state of everything above at any
time.

## 5. Update and uninstall

```bash
polyctl update --dry-run                  # how polyctl was installed, and the command that updates it
polyctl update                            # shows that command and asks; --yes runs it without asking
polyctl uninstall                         # a dry run: each job, hook and MCP entry it would take
polyctl uninstall --yes                   # take them off; --purge also deletes ~/.polyctl
```

`polyctl update` needs nobody to remember how polyctl went on. A git clone - the README's symlink to
`bin/polyctl` - is fast-forwarded with `git pull --ff-only`, and refused while it has uncommitted
changes, is on no branch or tracks nothing; a Homebrew, pipx or uv install is upgraded by its own
tool; a pip install by the pip of the interpreter running polyctl, with `--user` when it went into the
user's site directory. The command is printed before it runs.

`polyctl uninstall` takes off what polyctl set to run or load without anyone asking: its scheduled jobs, its
hooks in every project the machine registry knows - only files that are polyctl's exact bytes and
untracked, so a hook you edited stays - and the `polyctl` entry `polyctl init` put into their MCP files. Run
it before removing the program: once polyctl is gone, an enrolled project's hook fails every commit with
"polyctl not found". It names what it leaves: each project's `.polyctl/`, ledgers, mailbox and marker
(`polyctl remove --yes` in the project takes those, while polyctl is installed), `~/.polyctl` unless `--purge`,
and the program itself, with the command that removes it.

*In polyctl since slice UPDATE-UNINSTALL: `polyctl update` and `polyctl uninstall`. Update asks about the polyctl that
runs it, not the first one on PATH. Uninstall takes every launchd job in polyctl's namespace, those of
projects deleted since included, and on Linux every systemd user unit in it the same way
(LINUX-SCHEDULER); on Windows, where Task Scheduler has no namespace to list, the tasks of the
projects the registry knows. A systemd unit you wrote to run polyctl yourself is not polyctl's and stays, and
the dry run says so. A hook polyctl cannot prove untracked - one in a hooks directory outside
every repository - stays too, named, and the uninstall exits 1, as it does for anything it leaves
behind; `--purge` then keeps `~/.polyctl`, whose registry is how the next run finds what was left.*

*In polyctl since slice UPDATE-UNINSTALL-2: an MCP entry is polyctl's when it runs `polyctl … mcp serve`, with nothing after
it but polyctl's own `--role` and `--allow-verify`, whatever its command is called. An entry named `polyctl` whose
program was another one called polyctl was taken for polyctl's on its name alone, and removed. `polyctl remove --yes` finds
a project's entries as the uninstall does, under the key each adapter declares, and a file it cannot read
stays, named, and the removal exits 1.*

*In polyctl since slice LEADS-INSTALL: an entry is the project's only when the `-C` right before `mcp serve`
names that project, as every registration `polyctl init` wrote does: one serving another project, or any
program whose arguments end in `mcp serve`, was taken and removed with it. The file is found again as it
is written, and must lie in the project: a link swapped in after the removal began sent the write
outside. On macOS and Linux each directory from the project down is opened without following a link;
Windows pins each folder with native handles that prevent its replacement. MCP edits and project state
deletions use these held folders and refuse where neither backend is available. A change another program made to the file meanwhile
is not written over: the new file is written and synced first, and the file is read again as the last
thing before it is replaced or deleted. A file that changed stays as it now is, named, and the removal
exits 1. What files cannot close is the instant between that reading and the rename, a few system calls
long: a program that replaces the file in it loses its change, and no lock helps, since the harnesses
and editors that write these files take none. A file emptied of polyctl's entry is deleted with its
directory synced on macOS and Linux, as a file polyctl replaces is.*

## 6. Shell completion

```bash
mkdir -p ~/.zfunc && polyctl completion zsh > ~/.zfunc/_polyctl    # and fpath=(~/.zfunc $fpath) before compinit
mkdir -p ~/.local/share/bash-completion/completions && polyctl completion bash > ~/.local/share/bash-completion/completions/polyctl
polyctl completion fish > ~/.config/fish/completions/polyctl.fish
```

In PowerShell the line `polyctl completion powershell | Out-String | Invoke-Expression` goes into the
profile `$PROFILE` names. bash loads the file above through the bash-completion package; without it,
source the file from `~/.bashrc`.

*In polyctl since slice SHELL-COMPLETION: `polyctl completion <shell>` prints a script generated from polyctl's own
parser each time it runs - the commands, their long options and the choices each declares - so a
script is as current as the polyctl that printed it: print it again after `polyctl update`. Completing a word
runs no program, polyctl included, and reads no project. Every word from the parser is written into the
script as a literal quoted for its shell, and every word the script completes is quoted again on the
command line, so a choice holding a quote or a `$` can neither break the script nor run anything.
Where a word has no choices, the shell completes file names.*

*In polyctl since slice LEADS-OPS: a script knows how many words each option takes - the next alone, an
optional one that does not begin with `-`, a count, each word up to the next option, as
`polyctl review --paths` takes, or every word after it - and completes each of them as that option's.
Every option that took any word was taken for one that takes the next alone, so the word after
`polyctl review --paths a.py` was offered `polyctl review`'s actions instead of a file name.*
