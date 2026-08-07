# Repository conventions

Deliberately says nothing about disposition, tone, or how to treat people. This
is the control condition: it occupies the same slot in the prompt, and costs
roughly the same number of tokens, as a persona file — but carries no personality
content at all. If the profile moves under this file the way it moves under
`warm.md`, the effect is prompt perturbation, not persona.

## Formatting

- Two-space indent in TS/JS/JSON/YAML, four in Python. No tabs.
- Max line length 100. Break at the outermost call, not the innermost argument.
- Trailing commas in multi-line literals; none in single-line.
- One blank line between top-level declarations, two in Python modules.

## Naming

- `camelCase` for TS/JS locals and functions, `PascalCase` for types and React
  components, `SCREAMING_SNAKE` for module-level constants.
- `snake_case` throughout Python, including test names.
- Booleans read as predicates: `isReady`, `hasSchema`, `shouldRetry`.
- No abbreviations except the established ones: `id`, `url`, `db`, `req`, `res`.

## Imports

- Standard library, then third-party, then local; blank line between groups.
- Absolute paths from the package root. Relative imports only within a leaf module.
- No wildcard imports anywhere.

## Commits

- Imperative subject under 72 characters, no trailing period.
- Body wraps at 72. Explain why, not what — the diff already says what.
- One logical change per commit. Formatting-only changes go in their own commit.

## Tests

- Test files sit next to the code as `<name>.test.ts` / `test_<name>.py`.
- One assertion concept per test; name the test after the behaviour it pins.
- No network in unit tests. Fixtures live in `tests/fixtures/`.
