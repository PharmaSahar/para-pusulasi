# Runtime Storage Contract

## Purpose

Separate runtime-generated outputs from tracked repository content.

## Tracked Repository Files (Read-Only During Runtime)

Examples:
- docs/*
- README.md
- CHANGELOG.md
- CONTRIBUTING.md
- checked-in dashboards and documentation snapshots

Rule:
- Runtime code must not write to tracked repository paths.

## Runtime Files (Writable During Runtime)

Examples under runtime root:
- output/runtime/state/*
- output/runtime/telemetry/*
- output/runtime/logs/*
- output/runtime/evidence/*

Environment:
- runtime root is configurable via RUNTIME_OUTPUT_ROOT.
- if unset, default runtime root is output/runtime.

## Path Resolution Rules

- Runtime writers must resolve destinations through shared runtime path abstraction:
  - src/runtime_storage.py
- Runtime defaults are runtime-root relative.
- No runtime writer may hardcode docs/production_dashboard_latest.md as output target.

## Guard Rules

- Runtime write attempts into tracked paths are blocked.
- Development/test mode: raise TrackedRuntimeWriteError.
- Production mode: log configuration error and refuse write (fail closed for that write, process continues).

## Export Rules (Explicit Release Operation)

- Tracked docs update is allowed only through explicit export workflow.
- Export operation copies runtime dashboard to docs/production_dashboard_latest.md.
- Export uses safe overwrite with tmp+replace (atomic move semantics).
- Export is never called by scheduler automatically.

## Test Isolation Rules

- Tests must use tmp_path or isolated runtime directories.
- Tests should assert runtime dashboard path outcomes, not tracked docs mutation.
- No test should mutate repository tracked docs in-place.
