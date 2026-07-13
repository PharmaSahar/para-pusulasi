# Production Observability Hardening Report

Date: 2026-07-12
Scope: Observability-only instrumentation for incidents, Telegram formatting, and structured diagnostics.

## 1. Implementation Summary

Implemented in:
- src/scheduler_utils.py
- scheduler.py
- src/pipeline.py

Added capabilities:
- Global Incident ID (UUID) lifecycle state.
- Lifecycle transitions:
  - INCIDENT OPEN
  - INCIDENT UPDATED
  - INCIDENT RESOLVED
- Structured incident JSONL events for dashboards.
- Operator-friendly Telegram alert format with retry/regeneration counters.
- Enriched topic_provenance_collision diagnostics.
- Incident metrics snapshot generation:
  - collisions/hour
  - collisions/channel
  - regeneration success rate
  - retry success rate
  - mean recovery time
  - top collision reasons

## 2. Incident Lifecycle Examples

### Example INCIDENT OPEN

{
  "timestamp": "2026-07-12T09:25:24Z",
  "incident_id": "f4a72c72-86f2-4d8d-8cbf-dff3b052f6e2",
  "run_id": "run_11437f6292b342f1a0d8575d8776cce0",
  "channel": "Teknoloji Pusulasi",
  "pipeline_stage": "content_generation",
  "severity": "WARNING",
  "event_type": "incident_opened",
  "decision": "continue_with_backoff",
  "duration_ms": 0,
  "retry_count": 1,
  "regeneration_count": 0,
  "incident_lifecycle": "INCIDENT_OPEN"
}

### Example INCIDENT UPDATED

{
  "timestamp": "2026-07-12T09:26:05Z",
  "incident_id": "f4a72c72-86f2-4d8d-8cbf-dff3b052f6e2",
  "run_id": "run_11437f6292b342f1a0d8575d8776cce0",
  "channel": "Teknoloji Pusulasi",
  "pipeline_stage": "content_generation",
  "severity": "WARNING",
  "event_type": "incident_updated",
  "decision": "continue_with_backoff",
  "duration_ms": 0,
  "retry_count": 2,
  "regeneration_count": 0,
  "incident_lifecycle": "INCIDENT_UPDATED"
}

### Example INCIDENT RESOLVED

{
  "timestamp": "2026-07-12T09:26:02Z",
  "incident_id": "f4a72c72-86f2-4d8d-8cbf-dff3b052f6e2",
  "run_id": "run_11437f6292b342f1a0d8575d8776cce0",
  "channel": "Teknoloji Pusulasi",
  "pipeline_stage": "upload",
  "severity": "INFO",
  "event_type": "incident_resolved",
  "decision": "resolved_after_successful_upload",
  "duration_ms": 312000,
  "retry_count": 2,
  "regeneration_count": 0,
  "incident_lifecycle": "INCIDENT_RESOLVED"
}

## 3. Enriched topic_provenance_collision Example

{
  "timestamp": "2026-07-12T13:21:36Z",
  "incident_id": "99c8d7f3-1dd4-4fe9-9919-8d64cb881f37",
  "run_id": "run_ef1660cef394439ba11ee1a55d4cf151",
  "channel": "teknoloji_pusulasi",
  "pipeline_stage": "content_generation",
  "severity": "WARNING",
  "event_type": "incident_updated",
  "decision": "continue_with_monitoring",
  "duration_ms": 0,
  "retry_count": 1,
  "regeneration_count": 0,
  "incident_lifecycle": "INCIDENT_UPDATED",
  "error_type": "topic_provenance_collision",
  "expected_channel": "teknoloji_pusulasi",
  "detected_channel": "teknoloji_pusulasi",
  "selected_topic": "Yapay zeka araclariyla verimlilik",
  "original_topic_source": "anthropic",
  "provenance_score": null,
  "confidence_score": null,
  "triggering_validator": "topic_provenance_validator",
  "retry_number": 1,
  "regeneration_number": 0,
  "decision_taken": "continue_with_monitoring",
  "next_action": "Ayni hata tekrarlarsa manuel inceleme",
  "collision_diagnostics": "cross-channel cache reuse"
}

## 4. Sample Operator-Friendly Telegram Message

🚨 INCIDENT UPDATED
📌 Severity: WARNING
🆔 Incident ID: 99c8d7f3-1dd4-4fe9-9919-8d64cb881f37
📺 Kanal: Teknoloji Pusulasi
🧩 Error Type: topic_provenance_collision
❌ topic_provenance_collision:[path_hidden]
🧭 Decision: Uretim devam, izleme artirildi
🔧 Next Action: Ayni hata tekrarlarsa manuel inceleme
🔁 Retry: 1/3
♻️ Regeneration: 0/1

Note: raw file paths are hidden unless PRODUCTION_ALERT_DEBUG_MODE is enabled.

## 5. Dashboard Readiness Outputs

Produced files:
- logs/production_incidents.jsonl
- output/state/incident_state.json
- output/state/incident_metrics_latest.json

JSONL records are structured and machine-aggregatable (no text parsing required).

## 6. Validation Evidence

Business-logic policy unchanged:
- No retry policy threshold changes.
- No regeneration policy threshold changes.
- No fail-open/fail-close decision logic changes.
- No rendering/upload scheduler behavior changes.

Regression check:
- 46 tests passed:
  - tests/test_scheduler_provider_guardrails.py
  - tests/test_content_generator_anthropic_guard.py
  - tests/test_pipeline_telemetry_fail_open.py

## 7. Notes

This change set is observability hardening only. Any new output volume is in diagnostics/alerts, not control flow.
