# Collector Contract and Extension Guide

## Raw Observation Contract

Each collector must emit this shape:

```json
{
  "schema_version": 1,
  "source": "collector_source_name",
  "observed_at": "2026-07-08T12:00:00+00:00",
  "raw": {
    "topic": "example topic",
    "...": "source specific payload"
  }
}
```

Required constraints:
- schema_version must equal 1
- source must be a non-empty string
- observed_at must be ISO-like string
- raw must be an object

Validation helper:
- src/collector_contract.py

## Collector Rules

All new collectors must be passive:
- no production flow modifications
- no scoring
- no backlog generation
- fail-open on fetch errors

Persistence rule:
- write through append_raw_observation in src/research_db.py

## How to Add a New Collector

1. Create source file under src/ (example: src/new_source_collector.py)
2. Emit contract-shaped raw observation objects
3. Persist with append_raw_observation(...)
4. Add tests with static payloads (no external API calls)
5. Optionally register in src/research_scheduler.py if passive and covered by tests
6. Run relevant tests + research regression set

## Test Expectations for New Collectors

- contract conformance
- append-only file write confirmation
- fail-open behavior on fetch errors
- scheduler registration coverage (if added)

## Replay Compatibility

Use fields consistently so replay can filter and summarize reliably:
- source
- schema_version
- observed_at

This ensures old and new events stay analyzable across schema evolution.
