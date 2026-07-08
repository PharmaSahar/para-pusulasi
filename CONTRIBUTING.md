# Contributing

Thanks for contributing to this repository.

## Branch Naming

Use short, purpose-driven names:

- `feature/<topic>` for new capabilities
- `fix/<topic>` for bug fixes
- `docs/<topic>` for documentation-only changes
- `chore/<topic>` for maintenance
- `release/<version>` for release prep

For v0.2.0 work, branch from `v0.2.0-planning` unless explicitly instructed otherwise.

## Commit Message Convention

Use concise Conventional Commit style:

- `feat: add product hunt collector`
- `fix: handle empty reddit payload`
- `docs: update collector contract guide`
- `test: add replay determinism coverage`
- `chore: adjust CI matrix`

Rules:
- Keep subject line under ~72 chars.
- One logical change per commit.
- Prefer small, reversible commits.

## Test Expectations

Before opening a PR:

- Run the relevant tests for your change.
- If research pipeline behavior is touched, run the research regression set.
- Do not merge if tests fail.
- Add or update tests when behavior changes.

## Passive Research Constraints

For research-related changes:

- Keep collectors passive.
- Do not modify production publishing flow.
- Do not add automated scoring/ranking decisions in production path.
- Do not auto-generate execution backlog from research events.
- Preserve fail-open behavior where defined.

If a proposal needs to break these constraints, open an issue first and mark it as architecture-impacting.
