# Topic Provenance Fix Report

Status: patch_ready_tested_preproduction
Date: 2026-07-11
Scope: topic provenance hardening and runtime attribution integrity

## Objective
Implement immutable, run-scoped topic provenance with fail-closed selection behavior and runtime build identity attribution.

## Implemented Changes
- Immutable provenance persistence in `src/content_generator.py`:
  - Writes per-run evidence to `output/topic_provenance/<channel_id>/<run_id>/<content_id>.json`.
  - Rejects path collision with `topic_provenance_collision` (fail-closed).
  - Persists:
    - provider identity,
    - raw provider rows,
    - normalized rows,
    - pre-filter candidates,
    - rejected candidates with reason codes,
    - post-filter candidates,
    - fallback metadata,
    - selected topic/index,
    - runtime build identity payload.
- Hash integrity:
  - SHA256 component hashes for critical provenance arrays and runtime identity.
  - SHA256 payload hash over final persisted body.
- Runtime attribution in `src/pipeline.py`:
  - Attached runtime build identity fields into pipeline result and telemetry payload:
    - `git_sha_full`, `git_sha_short`, `process_pid`, `process_started_at_utc`, `python_executable`, `working_directory`.
- Backward compatibility:
  - Pipeline can instantiate test doubles that do not accept `provenance_context`.
  - Content generator defensively handles instances created via `__new__` in legacy tests.

## Evidence (Tests)
Strict targeted suites (`-W error`):
- `tests/test_topic_provenance.py`
- `tests/test_content_generator_prompting.py`
- `tests/test_scheduler_topic_domain_guard.py`
- `tests/test_scheduler_provider_guardrails.py`
- `tests/test_scheduler_cli.py`
- `tests/test_pipeline_telemetry_fail_open.py`
- `tests/test_pipeline_quality_integration.py`
- `tests/test_pipeline_experiment_registry_integration.py`

Result: 73 passed.

Full regression:
- `pytest -q -W default` => 589 passed.
- `pytest -q` => 589 passed.
- `git diff --check` => clean.

## Provenance Guarantees (Post-Fix)
- Every selected topic has run/content-scoped provenance when run context is present.
- Topic selection evidence includes both accepted and rejected candidates with explicit reason codes.
- Collision on existing provenance artifact blocks run progression (no overwrite).
- Runtime identity is serialized with topic provenance and emitted via telemetry.

## Maturity Label
REPORTED

Rationale:
- Code and tests prove implementation correctness in pre-production.
- No live production runtime artifact set was attached in this report; therefore not promoted to PROVEN/VALIDATED.
