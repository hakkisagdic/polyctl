# Checking a slice's spec

`polyctl spec check <slice>` reads one board item's Markdown spec without writing,
running tests or fetching sources. It prints PASS, FAIL or WARN and names each gap.
Feature and enterprise findings exit 1; bugfix and poc findings warn and exit 0.
An unknown or duplicate board id exits 2. An unknown work type fails closed.

Declare the work type and, optionally, the spec path on the board row:

```text
- [STORE-1] preserve rows on retry · work-type: feature · spec: docs/specs/STORE-1.md
```

The four work types are `feature`, `enterprise`, `bugfix` and `poc`. The default spec
path is `docs/specs/<slice>.md`; an explicit `spec:` path must stay inside the project,
including through symlinks. A spec must be a regular UTF-8 file of at most 1 MiB.
An explicit check with no work type uses feature requirements.

Before a prospective review starts, both `polyctl review` and `polyctl review submit`
run the same check for a row carrying `work-type:` or `spec:`. A feature or enterprise
failure starts no reviewer. Legacy rows with neither field keep their existing
acceptance-boundary behavior. Submitted reviews check at submission; the background
runner does not check the next running slice. Retrospective reviews keep their landed
boundary. This is a spec readiness check, not a persisted commit grant or a replacement
for the independent review of the exact staged candidate. It reads the working spec;
the existing `boundary: path@commit` contract remains separate.

## Spec format

The default required sections are Problem, Acceptance criteria, Out of scope, Tests
and Risks. Headings are case insensitive; hyphens and underscores count as spaces.
Each required section must contain prose. Fenced examples and HTML comments supply
no evidence. Nested headings may organize a section.

Write each acceptance criterion as a list item or a separate paragraph. Wrapped lines
belong to the same item. Each needs either a `path::name` test reference (including
class names and parameter ids), or a test id declared in Tests. Supported ids are
`T1` (any digits), `TEST-retry` (letters, digits, underscores and hyphens), and
`test_retry` (letters, digits and underscores). One test may cover several criteria,
but mentioning a test somewhere else in the spec does not cover a criterion.

Put claims about external systems in an External claims section, one list item or
paragraph per claim, or start the claim with `External:` elsewhere. Each claim needs
an HTTP(S) source URL or a Markdown reference whose definition contains one. A Sources
section alone does not cover an unlinked claim. The checker does not infer unmarked
claims from arbitrary prose, confirm that a citation supports a claim, or prove that
a named test exists or passes; those remain the reviewer and verification gates' work.

```markdown
# STORE-1

## Problem
Rows can be lost on retry.

## Acceptance criteria
- AC-1: a retry preserves every row (T1).
- AC-2: empty input returns no rows (tests/test_store.py::test_empty).

## Out of scope
Changing the storage engine.

## Tests
- T1: tests/test_store.py::test_retry
- tests/test_store.py::test_empty

## Risks
Clients might retry concurrently.

## External claims
- The service documents its retry behavior [service].

[service]: https://example.invalid/service/retries
```

## Requirements per work type

The project configuration accepts `work_types`, keyed by work type, with a
`required_sections` list in each entry. For example, an enterprise entry can require
the five default headings plus `rollout`; a poc entry can require only `problem`,
`acceptance criteria` and `tests`. Omitted entries use all five defaults. An empty
list removes heading requirements; acceptance criteria still need test traces and
external claims still need sources. Invalid configuration is reported, never silently
replaced with weaker requirements.
