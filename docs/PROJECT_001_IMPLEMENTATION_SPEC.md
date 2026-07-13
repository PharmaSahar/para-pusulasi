# PROJECT 001 IMPLEMENTATION SPEC

Project ID: 001
Project name: Governance Integrity Hard-Fail
Source of truth:
- docs/COMPLETE_SYSTEM_REVIEW_FINAL.md
- docs/MASTER_EXECUTION_PLAN_v1.md
Date: 2026-07-13
Execution status: Ready for coding (spec only)

---

## Project Selection Verification

Selected project:
- Project 1.1 Governance Integrity Hard-Fail (Phase 1 Production Stability)

Why this is still first priority:
- Final review marks this as a verified P0 risk: required governance artifacts can pass via fallback.
- Master plan states this is the highest-ROI single project and prerequisite for trustworthy go/no-go decisions.
- Current repository still shows fallback-pass logic in ops/refresh_governance_readiness.py and current warning evidence in docs/governance_readiness_latest.md.

Decision:
- Keep Project 001 as first execution project.

---

## Objective

Eliminate false-positive governance readiness outcomes by enforcing strict hard-fail behavior for all required governance producer steps.

## Business Value

- Prevents incorrect production go decisions.
- Protects leadership trust in readiness metrics.
- Reduces downstream execution waste caused by invalid evidence.

## Technical Goal

Change governance refresh execution semantics so required steps only pass when the producer command actually executes successfully, not when a fallback artifact exists.

## Current Behavior

- Missing required producer scripts can still return pass if fallback artifact exists.
- Snapshot can report required_steps_passed as successful even when producer was not executed.
- Markdown can show PASS with warning script_missing_fallback_artifact_used.

## Desired Behavior

- Required step missing script always fails with non-zero exit and explicit hard-fail reason.
- Required step execution failure always fails regardless of fallback artifact existence.
- required_steps_passed and overall ok reflect strict required producer execution truth.
- Optional steps may remain fail-open where intended.

---

## Exact Repository Modules

- ops.refresh_governance_readiness
- src.runtime_storage (path behavior dependency, no primary logic ownership)

---

## Files Expected to Change

Primary expected code files:
- ops/refresh_governance_readiness.py

Primary expected tests:
- tests/test_refresh_governance_readiness.py

Optional additional tests if needed for isolation clarity:
- tests/test_governance_dashboard_safety.py

No source runtime migration in this project scope:
- No schema migration outside this module.
- No production deployment scripts changed in Project 001.

---

## Runtime Impact

Expected runtime behavior changes:
- Governance refresh may fail in environments currently relying on fallback artifacts for required steps.
- Monitor and latest snapshot will become stricter and may initially show lower pass rates.

Expected observability changes:
- Warnings and failure codes become explicit and actionable for required step failures.

---

## Production Impact

Positive impact:
- Readiness signal integrity increases immediately.
- Reduces risk of releasing or scaling based on stale/incomplete evidence.

Short-term operational impact:
- Potential increase in visible failures until missing producer scripts or dependencies are fixed.

---

## Safety Constraints

1. Do not relax fail-closed behavior for required steps.
2. Preserve fail-open behavior for optional steps unless explicitly changed by separate project.
3. Do not change unrelated governance artifacts or roadmap logic in this project.
4. Do not alter scheduler, pipeline, upload, or rendering logic.
5. Keep output schema backward-safe where possible; if fields change, add compatibility notes in tests.

---

## Required Tests

Unit and behavior tests to add or update:

1. Required step with missing script and existing fallback artifact must fail.
2. Required step with missing script and no fallback artifact must fail.
3. Required step with command execution failure must fail.
4. Optional step with missing script and fallback artifact may pass only if fail_open is true.
5. run_refresh overall ok must be false when any required step fails.
6. required_steps_passed and required_steps_total must reflect strict semantics.
7. Markdown step table must report FAIL for required step hard-fail cases.
8. Existing strict evidence bridge artifact assertions must continue to pass where unrelated.

Execution target:
- pytest tests/test_refresh_governance_readiness.py
- pytest tests/test_governance_dashboard_safety.py

---

## Runtime Validation

Post-implementation validation sequence:

1. Execute governance refresh command in controlled environment.
2. Inspect latest payload:
- required_steps_passed
- required_steps_total
- ok
- per-step exit_code and warning
3. Inspect generated readiness markdown for required-step PASS/FAIL accuracy.
4. Verify that environments missing required producers now surface hard failures.
5. Verify optional steps still behave according to fail_open policy.

Evidence artifacts to inspect:
- output/runtime/state/governance_refresh_run_latest.json
- output/runtime/state/governance_readiness_latest.md
- output/runtime/telemetry/proven_validated_monitor.jsonl

---

## Rollback Boundary

Rollback trigger conditions:
- Unintended blocking of all governance runs due to non-required path regressions.
- Evidence that strict behavior incorrectly marks successful required runs as failed.

Rollback method:
- Revert Project 001 code changes to prior semantics.
- Keep generated artifacts for audit trace.

Rollback scope:
- Limited to ops/refresh_governance_readiness.py and related tests changed in this project.

---

## Acceptance Criteria

1. Required-step fallback artifact no longer causes PASS when producer script is absent.
2. Required-step failures reliably force overall ok=false.
3. Optional-step fail-open behavior remains intact.
4. Tests for strict required semantics pass.
5. Runtime artifacts reflect strict pass/fail truth with explicit warnings.

---

## Definition of Done

Project 001 is done when all conditions below are met:

1. Code and tests implementing strict required-step hard-fail are merged.
2. Test suite for governance refresh passes with new strict scenarios.
3. Runtime validation confirms hard-fail behavior on missing required producers.
4. No unrelated subsystem behavior changes are introduced.
5. Rollback procedure is documented and confirmed executable.

---

## Implementation Slices

All slices are designed to be independently testable, reviewable, deployable, and rollbackable.

### Slice 1 - Required-Step Decision Logic Hardening

Scope:
- Modify required-step evaluation logic so fallback artifacts never convert missing/failed required producer execution into PASS.

Independence:
- Testable via unit tests targeting _run_step and run_refresh required path outcomes.
- Deployable as logic-only change in one module.
- Rollbackable by reverting one logical change set.

Estimated complexity:
- Medium

Dependencies:
- Existing refresh_governance_readiness module behavior

Risk:
- Medium (initial increase in surfaced failures)

Expected business value:
- Very High (removes P0 false-readiness risk)

### Slice 2 - Snapshot and Reporting Semantics Alignment

Scope:
- Ensure snapshot counters and warning semantics cleanly represent strict required failure behavior.
- Ensure markdown status output aligns with strict required semantics.

Independence:
- Testable by fixture-driven payload checks and markdown output assertions.
- Deployable without changing scheduler/pipeline.
- Rollbackable to previous reporting semantics without touching core pipeline.

Estimated complexity:
- Medium

Dependencies:
- Slice 1 decision outcomes available

Risk:
- Low-Medium (consumer expectations on warning fields)

Expected business value:
- High (decision transparency and auditability)

### Slice 3 - Regression Safety and Operator Validation Pack

Scope:
- Add/extend tests covering required vs optional behavior matrix.
- Add runtime validation checklist output requirements for post-deploy verification.

Independence:
- Testable via dedicated pytest targets.
- Deployable as test and validation support layer.
- Rollbackable by reverting test/validation additions.

Estimated complexity:
- Medium

Dependencies:
- Slice 1 and Slice 2 completed

Risk:
- Low

Expected business value:
- High (stability and confidence for production rollout)

---

## Slice 1 Detailed Implementation Specification (Selected)

Slice selected for immediate implementation planning:
- Slice 1 Required-Step Decision Logic Hardening

In-scope behaviors:
1. In _run_step, when required is true and script path is missing:
- exit_code must be non-zero
- warning must identify script missing hard-fail
- fallback artifact existence must not convert result to success
2. In run_refresh, required-step pass accounting must rely on strict exit_code semantics only.
3. Optional fail-open behavior must remain unchanged.

Out-of-scope for Slice 1:
- Markdown wording redesign beyond correctness of PASS/FAIL output.
- Broader governance dashboard redesign.
- Any analytics, scheduler, upload, or runtime storage feature work.

Slice 1 test plan:
1. Add/update test where required step script missing with fallback artifact currently PASS behavior becomes FAIL.
2. Add/update test for run_refresh overall ok false when any required hard-fail occurs.
3. Add regression test ensuring optional fail-open path remains permitted.

Slice 1 acceptance gate:
- All Slice 1 tests pass.
- No unrelated tests regress.
- Manual local dry run shows required missing producer produces FAIL and ok=false.

Slice 1 rollback boundary:
- Revert only logic changes for required-step fallback handling and related tests.

---

End of PROJECT_001 implementation spec.
