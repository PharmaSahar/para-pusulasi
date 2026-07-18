# PROJECT003 Visual-Safety Containment Control Runbook

## Purpose

This runbook documents the official runtime mechanism for releasing and restoring only the PROJECT003 visual-safety incident containment.

## Scope

The tool is scoped to incident `PROJECT003` and pause reason `visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals`. It must not clear arbitrary overload pauses, provider rate-limit pauses, provider failure history, queues, quarantine records, credentials, tokens, or runtime evidence.

## Prerequisites

- Production must be on the expected immutable release SHA.
- `parapusulasi` service must be active and running.
- `/opt/parapusulasi/deploy.lock/.active_lock` must be absent.
- Production Observation Mode must be enabled by the official CLI for the first observation window.
- Uploads, Shorts uploads, final renders, queue mutation, registry writes, analytics writes, and publication actions must be blocked by `PRODUCTION_OBSERVATION_MODE`.
- Fresh release eligibility evidence must pass schema validation.
- Quarantined jobs must remain untouched.

## Status

Status is read-only and writes no audit record:

```bash
python tools/visual_safety_containment.py status --incident-id PROJECT003
```

The status output includes the current production observation-mode state.

## Production Observation Mode

Production Observation Mode is the canonical runtime control for the no-upload/no-render release window. The mode is derived from `PRODUCTION_OBSERVATION_MODE` and the official persisted state file `output/state/production_observation_mode.json` unless overridden by `PRODUCTION_OBSERVATION_MODE_STATE_FILE`.

Enable it before release:

```bash
python tools/visual_safety_containment.py enable-observation \
  --incident-id PROJECT003 \
  --operator "<operator identity>" \
  --reason "PROJECT003 controlled no-upload/no-render release window" \
  --expected-production-sha <sha>
```

When enabled, the production safety gate allows scheduler startup and read-only safety checks, but blocks irreversible side-effect operations with reason `production_observation_mode`: final render, upload, Shorts upload, publication, registry update, analytics write, and queue mutation.

Disable it only after the controlled observation passes, or after restore if observation fails:

```bash
python tools/visual_safety_containment.py disable-observation \
  --incident-id PROJECT003 \
  --operator "<operator identity>" \
  --reason "PROJECT003 controlled observation passed" \
  --expected-production-sha <sha>
```

## Eligibility Evidence

Evidence must use schema `visual_safety_containment_release_evidence.v1`, match the production SHA and policy version, be fresh within the documented validity window, set `eligible_for_release=true`, include all mandatory booleans, and report zero unsafe selections, unsafe approvals, upload attempts, quarantine escapes, and critical runtime errors.

Validate evidence before release:

```bash
python tools/visual_safety_containment.py validate-release-eligibility \
  --incident-id PROJECT003 \
  --expected-policy-version visual_safety.v1 \
  --expected-production-sha <sha> \
  --evidence-file <eligibility-evidence.json>
```

Generate fresh evidence from the deployed release into a runtime path outside Git:

```bash
python tools/visual_safety_containment.py generate-eligibility-evidence \
  --incident-id PROJECT003 \
  --expected-production-sha <sha> \
  --output-file /opt/parapusulasi-shared/runtime/output/runtime/state/project003_release_evidence.json \
  --logs-since "2026-07-18 09:10:40 UTC"
```

## Release

Release uses a filesystem lock, rereads state under lock, validates expected state, atomically writes `provider_health.json`, preserves unrelated provider state, and appends an audit record.

Release fails closed unless Production Observation Mode is enabled. The `--uploads-disabled` and `--renders-disabled` flags are assertions; they are not substitutes for the active observation-mode runtime control.

```bash
python tools/visual_safety_containment.py release \
  --incident-id PROJECT003 \
  --expected-reason visual_safety_incident_containment:PROJECT003:cross_channel_inappropriate_visuals \
  --expected-policy-version visual_safety.v1 \
  --expected-production-sha <sha> \
  --operator "<operator identity>" \
  --evidence-file "<eligibility evidence JSON>" \
  --uploads-disabled \
  --renders-disabled \
  --confirm-release PROJECT003
```

Expected output includes `status=released`, an audit event ID, and before/after state hashes.

## Audit Path

Audit records are append-only JSONL at `output/runtime/telemetry/visual_safety_containment_audit.jsonl` unless overridden by `VISUAL_CONTAINMENT_AUDIT_FILE`. Records include event ID, operator, production SHA, policy version, evidence hash, state hashes, assertions, success/failure, and failure reason. Credentials and tokens must never be recorded.

## No-Upload Observation

After release, run exactly one controlled observation cycle with Production Observation Mode enabled, no final publication, no quarantine recovery, and no legacy unsafe asset reuse. Restore immediately if any unsafe selection, unsafe approval, upload attempt, render output, registry write, analytics write, queue mutation, cache contamination, quarantine escape, or critical runtime error occurs.

## Restore

Restore atomically reapplies PROJECT003 containment and appends an audit record:

```bash
python tools/visual_safety_containment.py restore \
  --incident-id PROJECT003 \
  --operator "<operator identity>" \
  --reason "<rollback reason>" \
  --expected-production-sha <sha> \
  --confirm-restore PROJECT003
```

## Failure Modes

The tool fails closed for unknown incident IDs, reason mismatches, SHA mismatches, policy mismatches, missing or stale evidence, false mandatory checks, nonzero unsafe/upload/quarantine/critical counts, active deploy lock, unhealthy service, missing confirmations, duplicate release requests, unknown pause types, and changed runtime state before lock acquisition.

## Rollback Procedure

If release verification or the no-upload observation fails, run the restore command immediately with the current production SHA and a specific rollback reason. Do not run additional scheduler cycles before restore.

## Prohibited Manual Actions

- Do not edit `provider_health.json` manually.
- Do not delete provider-health state.
- Do not change pause timestamps manually.
- Do not clear unrelated pauses.
- Do not restore quarantined jobs automatically.
- Do not enable uploads during first observation.
- Do not release containment unless Production Observation Mode is enabled.
- Do not manually edit `production_observation_mode.json`; use the CLI.
- Do not bypass evidence validation.