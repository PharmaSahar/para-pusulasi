# Telegram Incident Policy

Date: 2026-07-12
Scope: production incident lifecycle and cooldown policy for `src.scheduler_utils`.

## Identity
- Incident identity is derived from the stable fingerprint used by `_register_incident_event`.
- Fingerprint inputs are `channel_name`, `error_type`, `decision`, `run_id`, `content_id`, and `pipeline_stage`.
- `retry_count` and `regeneration_count` must not create a new incident identity.
- Different channels, content IDs, run IDs, decisions, error types, or pipeline stages may produce different incidents when the contract requires it.

## Lifecycle
- `OPEN` is emitted exactly once when a fingerprint first appears in incident state.
- `UPDATED` is emitted only for meaningful changes on an already-open fingerprint.
- `UPDATED` is not required for every retry.
- `UPDATED` is rate-limited per incident by the existing alert cooldown and incident state.
- `RESOLVED` is emitted exactly once after verified recovery for an open fingerprint.
- Duplicate recovery must not emit a second `RESOLVED` for the same already-resolved fingerprint.

## Telegram noise control
- Telegram payloads must surface channel, incident ID, decision, and relevant error context.
- Repeated retries for the same open fingerprint must not spam Telegram.
- A meaningful state change may produce one bounded `UPDATED` message.
- A verified recovery may produce one bounded `RESOLVED` message.
- A cooldown for a warning-class event must not hide a more severe critical event when the incident identity or decision differs.
- A resolved event must not be hidden by an open-event cooldown on the same fingerprint when recovery is verified.

## Path redaction
- Non-debug operator payloads must not leak raw absolute or relative filesystem paths.
- Debug mode may retain raw paths for incident forensics.

## Observability fail-open
- Incident-state write failures, alert-state write failures, malformed observability files, and telemetry send failures must not change scheduler business decisions.
- Business-flow decisions remain controlled by the scheduler and pipeline gates, not by observability persistence.
