<!--
Length-matched control for soul-sentinel.md.

soul-sentinel.md is ~10KB of genuine personality (Values, Personality, Tone).
ops-checklist.md is personality-free but only ~1.7KB, so on its own it cannot
separate "the persona content moved the profile" from "10KB of prepended text
moved the profile". This file occupies the same prompt position at the same
order of magnitude and says nothing whatsoever about disposition, tone, or how
to treat people — only mechanical repository convention.

A control is supposed to be boring. That is the job.
-->

# Repository conventions

## Formatting

- Two-space indent in TS/JS/JSON/YAML/CSS, four in Python. No tabs anywhere.
- Max line length 100 for code, 80 for Markdown prose.
- Break long calls at the outermost boundary, not the innermost argument.
- Trailing commas in multi-line literals; none in single-line.
- One blank line between top-level declarations in TS, two in Python modules.
- No blank line immediately after an opening brace or before a closing one.
- Sort object literal keys only when the object is a lookup table; preserve
  authored order when the keys form a sequence or a config shape.
- String quoting: double in TS/JSON, double in Python. Escape rather than
  switching quote style to avoid an escape.
- One statement per line. No comma operators, no chained assignment.

## Naming

- `camelCase` for TS/JS locals, parameters, and functions.
- `PascalCase` for types, interfaces, enums, classes, and React components.
- `SCREAMING_SNAKE` for module-level constants whose value is a literal.
- `snake_case` throughout Python, including test function names.
- Booleans read as predicates: `isReady`, `hasSchema`, `shouldRetry`, `canEdit`.
- Collections are plural; a single item is singular. No `dataList`, no `itemArr`.
- Abbreviations: only the established set — `id`, `url`, `db`, `req`, `res`,
  `ctx`, `env`, `cfg`. Spell out everything else.
- Acronyms in identifiers are capitalised as words: `HttpClient`, `parseXmlDoc`.
- Private module members are prefixed `_` in Python and are simply unexported
  in TS. Do not use `_` prefixes in TS.
- File names match their primary export: `UserCard.tsx`, `parse_manifest.py`.

## Imports and module layout

- Standard library, then third-party, then first-party, then relative. One
  blank line between groups.
- Absolute paths from the package root for anything outside the current
  module's directory. Relative imports only within a leaf module.
- No wildcard imports. No re-export barrels deeper than one level.
- Type-only imports use `import type` in TS so they erase at build time.
- Circular imports are a build error, not a warning. Break the cycle by
  extracting the shared type into its own module.
- Side-effectful imports appear first in the file and carry a trailing comment
  naming the effect.

## Errors and control flow

- Catch the narrowest exception type the call can raise. A bare `except:` or
  `catch {}` fails review.
- Never swallow an error to make a test pass. Either handle it or let it
  propagate with context attached.
- Error messages name the operation, the input, and the expected shape, in that
  order. `parse_manifest: expected key "cases", got ["case"]`.
- Prefer early return over nested conditionals. Maximum nesting depth is three.
- No control flow through exceptions for expected conditions — a missing
  optional key is a `None`, not a raise.
- Validate at the boundary (user input, external API, file parse) and trust
  internal callers after that. Do not re-validate the same value at every layer.

## Testing

- Test files sit next to the code: `<name>.test.ts`, `test_<name>.py`.
- One assertion concept per test. Name the test after the behaviour it pins,
  not the function it calls: `rejects a manifest with no cases`.
- Fixtures live in `tests/fixtures/` and are checked in, never generated at
  test time.
- No network calls in unit tests. Integration tests that need the network are
  marked and excluded from the default run.
- Snapshot tests are permitted only for serialised output whose shape is the
  contract. Never snapshot a rendered component tree.
- A regression test accompanies every bug fix and references the issue number
  in a comment above it.
- Test doubles: prefer a real object with narrow inputs over a mock. Mock only
  at process boundaries.
- Coverage is reported but not gated. A gate produces tests written for the
  gate.

## Version control

- Imperative subject under 72 characters, no trailing period.
- Body wraps at 72 columns. Explain why, not what — the diff already says what.
- One logical change per commit. Formatting-only changes go in their own commit
  so review can skip them.
- Branch names: `feat/`, `fix/`, `chore/`, `docs/` prefix followed by a
  kebab-case summary.
- Rebase local work before opening a pull request; merge commits inside a
  feature branch are noise.
- Never force-push a branch another person has based work on.
- Tag releases `v<major>.<minor>.<patch>` with an annotated tag carrying the
  changelog entry.

## Dependencies

- A new runtime dependency needs a one-line justification in the pull request
  describing what it replaces.
- Pin exact versions in lockfiles; ranges in manifests.
- Prefer the standard library where the standard library is within 20 lines of
  the dependency.
- Dev dependencies never appear in runtime imports; the build fails if they do.
- Audit output is reviewed at release, not ignored and not auto-merged.

## Logging and observability

- Structured logs only: a message plus key-value fields, never interpolated
  prose.
- Levels: `debug` for developer detail, `info` for state transitions, `warn`
  for recoverable anomalies, `error` for failed operations.
- Never log secrets, tokens, full request bodies, or personal data. Log the
  identifier, not the payload.
- Every outbound request logs its target, status, and duration.
- Metrics are counters and histograms. Gauges only for values that genuinely
  oscillate.

## Configuration

- Configuration comes from the environment. No environment detection in code —
  no `if (env === "production")` branches around behaviour.
- Every variable is read once at startup into a typed config object; nothing
  reads `process.env` or `os.environ` below that layer.
- Missing required configuration fails at startup with the variable name, not
  at first use.
- Defaults are for local development only and are never production-safe.

## Data and migrations

- Every schema change ships as a migration; no manual alterations.
- Migrations are forward-only and idempotent where the engine permits.
- A migration that drops a column ships one release after the code that stopped
  reading it.
- Foreign keys declare their cascade behaviour explicitly rather than relying on
  the engine default.
- Indexes are added with the query they serve named in a comment.

## HTTP and API surface

- Resource paths are plural nouns; actions are verbs on the method, not the
  path.
- Return the narrowest status that is accurate: `404` for a missing resource,
  `409` for a state conflict, `422` for a well-formed but invalid body.
- Every non-2xx response carries a JSON body with `error` and `code`. An empty
  body is a bug.
- Pagination is cursor-based. Offset pagination is permitted only for fixed,
  small collections.
- Breaking a response shape requires a new version path, not a flag.

## Documentation

- Every exported function has a docstring or JSDoc naming its inputs, its
  return, and what it raises.
- Comments explain why. If a comment restates the line below it, delete the
  comment.
- A comment marking a workaround names the upstream issue and the condition
  under which it can be removed.
- README covers install, run, test, and deploy in that order, and nothing else.
- Architecture notes live in `docs/`, one file per subsystem, updated in the
  same pull request as the change they describe.

## Performance

- Measure before optimising. A performance pull request includes the before and
  after numbers and the command that produced them.
- No premature caching. A cache needs a stated invalidation rule before it is
  added.
- Database access in a loop is a review blocker; batch or join instead.
- Async boundaries are explicit; do not fire and forget without a comment
  naming who observes the failure.
- Bundle size is budgeted per route; a pull request that exceeds the budget
  reports the delta and the largest contributing module.
- Images are served in the smallest format the target browsers accept, with
  explicit width and height attributes to avoid layout shift.

## Concurrency

- Shared mutable state is either behind a lock or not shared. There is no third
  option.
- Locks are acquired in a documented global order; nested acquisition follows
  that order without exception.
- Every lock acquisition has a timeout. An unbounded wait is a deadlock waiting
  for a scheduler.
- Background tasks register with the shutdown handler at creation. An orphaned
  task that outlives its owner is a leak.
- Retries use exponential backoff with jitter and a maximum attempt count.
  Fixed-interval retries synchronise across clients and amplify an outage.
- Idempotency keys accompany every retryable write so a duplicate delivery is a
  no-op rather than a second effect.
- Queue consumers acknowledge after the work commits, never before.

## Security

- Secrets come from the secret store at runtime; none appear in the repository,
  the image, or the build log.
- Every external input is parsed into a typed structure before use. String
  concatenation into SQL, shell, or HTML is a review blocker.
- File paths derived from input are resolved to their canonical form and
  verified to sit inside the intended root before any read or write.
- Dependencies with known advisories are upgraded or pinned with a documented
  exception naming the reviewer and the expiry date.
- Authentication and authorisation are separate checks. Passing the first never
  implies the second.
- Tokens carry the narrowest scope the operation needs and the shortest
  lifetime the workflow tolerates.
- Cryptographic primitives come from the platform library. No hand-rolled
  constructions, no reused initialisation vectors.

## Code review

- A pull request describes what changed and why, and names the reviewer's
  entry point — the file to read first.
- Diffs over 400 changed lines are split unless the change is mechanical and
  the description says so.
- Review comments distinguish blocking from non-blocking; a non-blocking note
  is prefixed `nit:`.
- The author resolves each thread; the reviewer confirms. Neither resolves the
  other's.
- Generated files are excluded from review via the diff attributes file rather
  than by asking the reviewer to skip them.

## Build and continuous integration

- The build is reproducible: the same commit produces the same artefact on any
  machine.
- Every check that gates merge runs locally with a single documented command.
- A flaky test is quarantined within one day and fixed or deleted within one
  week. A permanently retried test gates nothing.
- Build steps are cached by content hash, never by branch name.
- The pipeline fails loudly on a missing environment variable rather than
  substituting an empty string.
