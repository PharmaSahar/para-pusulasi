# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Operations
- OAuth incident closure documented for July 2026.
- Active-channel OAuth recovery verified with release/SHA/symlink unchanged.
- Analytics OAuth readiness explicitly tracked as separate follow-up.

## [0.1.0] - 2026-07-08

### Added
- Passive research foundation and append-only event store.
- Collector contract validation for raw observations.
- Passive Google Trends collector.
- Passive GitHub Trends collector.
- Passive Reddit Trends collector.
- One-shot passive research scheduler and manual runner.
- Research observation schema versioning (schema_version = 1).
- Passive replay engine with filters and fail-open invalid line handling.
- Replay metadata summary fields:
  - files_scanned
  - files_with_events
  - first_observed_at
  - last_observed_at
- Determinism and smoke coverage for replay and pipeline.
- Research regression CI workflow.

### Notes
- No production publishing flow changes in this release.
- No scoring or backlog generation automation introduced.

[Unreleased]: https://example.local/unreleased
[0.1.0]: https://example.local/releases/0.1.0
