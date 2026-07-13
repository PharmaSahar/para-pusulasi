# PROJECT 001 SLICE 1 DEPLOYMENT PLAN

Project: 001 Governance Integrity Hard-Fail
Slice: Slice 1 Required-Step Decision Logic Hardening
Prepared on: 2026-07-13
Execution status: PLAN ONLY - NOT DEPLOYED

## Deployment Scope

- Deployed production SHA before update: 6a7f8025d47f3789c265f74203501a10a943947c
- Target SHA: a170aeae1b51554f7a7116bc3e443b78c8839186
- Changed production file:
  - ops/refresh_governance_readiness.py
- Test-only commit (validated but non-production scope):
  - bf866d5522c3875cc2e94359690e1050198ddb50
- Documentation-only commit (non-production scope):
  - 6a7f8025d47f3789c265f74203501a10a943947c

## Deployment Intent

Deploy only the Slice 1 governance hard-fail behavior so required governance evidence can no longer pass via fallback artifact substitution.

## Required Predeploy Checks

1. Verify current live production SHA from the active host checkout.
2. Confirm target host uses the canonical production root.
3. Confirm no deployment is in progress and no conflicting worktree is active.
4. Run current production health check before change.
5. Confirm the validated test baseline for Slice 1:
   - Governance regression tests: 25 passed
   - Full suite: 661 passed
   - Strict suite: 661 passed
6. Confirm producer scripts expected by governance refresh are present on the target host.
7. Confirm operators understand that stricter required-step failures may surface previously masked producer gaps.

## Service Restart Requirement

- Restart requirement: YES
- Reason: governance refresh behavior is exercised by runtime operational scripts; the running service/process environment should be refreshed to ensure the updated repository state and code path are active consistently.

## Deployment Method

1. Verify live SHA and branch on target host.
2. Update target host checkout to target SHA `a170aeae1b51554f7a7116bc3e443b78c8839186`.
3. Restart the relevant scheduler/ops process from the canonical root.
4. Run governance refresh manually once in controlled mode.
5. Observe generated readiness outputs before declaring success.

## Runtime Governance Validation

After restart, run and inspect:

1. Governance refresh command in controlled mode.
2. Validate latest payload fields:
   - required_steps_passed
   - required_steps_total
   - ok
   - per-step exit_code
   - per-step warning
3. Validate required-step contract:
   - missing required producer must fail closed
   - required failures must not be counted as passed
   - optional fail-open paths remain explicitly warning-tagged
4. Inspect readiness markdown for PASS/FAIL correctness.

## Smoke Test

Minimum smoke test sequence:

1. Scheduler/ops health check passes.
2. Governance refresh runs successfully when required producers exist.
3. Simulated or known-missing required producer path results in hard-fail behavior.
4. Optional fail-open behavior still reports explicit warning rather than silent success.
5. No unexpected regressions in scheduler startup or governance dashboard generation.

## Rollback SHA

- Rollback SHA: b9cafcecff7d5593aba0d91ca33870e9df1f4332

## Rollback Command

Example rollback command sequence on target host:

```bash
git checkout b9cafcecff7d5593aba0d91ca33870e9df1f4332
# restart the relevant scheduler/ops process from the canonical root
```

Operational rollback trigger:
- strict required-step hard-fail behavior incorrectly blocks healthy required producer executions
- governance refresh becomes unusable due to non-spec regressions

## Observation Window

- Minimum observation window: 1 full governance refresh cycle immediately after deployment
- Recommended observation window: 24 hours of normal governance/reporting operation

## Acceptance Criteria

Deployment is accepted only if all conditions below are true:

1. Live target host is on target SHA.
2. Governance refresh executes from the intended root.
3. Required producer absence now fails closed.
4. Required failures are not counted as passed.
5. Optional fail-open behavior remains explicit and warning-tagged.
6. No scheduler or governance startup regressions appear.
7. Generated readiness outputs are internally consistent.
8. No rollback trigger is observed during the observation window.

## Notes

- The test-only commit `bf866d5522c3875cc2e94359690e1050198ddb50` does not require production deployment.
- The documentation-only commit `6a7f8025d47f3789c265f74203501a10a943947c` does not require production deployment.
- This plan prepares deployment only; it does not authorize or execute deployment.
