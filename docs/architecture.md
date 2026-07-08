# Architecture Overview

## Goal
Build a resilient Autonomous Media Operating System that grows autonomy without
breaking production stability.

## Current Operating Model

Two tracks run in parallel:

1. Production Track
- Existing production assets remain stable.
- No automatic destructive actions.
- No uncontrolled publication behavior.

2. Passive Research Track
- Collects and stores observations.
- Uses append-only event files.
- Supports replay for analysis and backtesting.
- Does not perform scoring-based decisions in production.

## Passive Research Components

- Collector contract:
  - source
  - schema_version
  - observed_at
  - raw
- Passive collectors:
  - google_trends
  - github_trends
  - reddit_trends
- Append-only event store:
  - research/raw/YYYY-MM-DD.jsonl
  - research/normalized/opportunities.jsonl
  - research/schema/opportunity_v1.json
- One-shot scheduler:
  - runs registered collectors once
  - fail-open per collector
  - returns structured summary
- Replay engine:
  - line-by-line JSONL reading
  - fail-open invalid JSON lines
  - filters by source, schema_version, observed_at range
  - metadata summary (files and observed_at bounds)

## Why Replay Matters

Replay enables:
- backtesting on historical observations
- safe scoring iteration without recollecting internet data
- reproducible debugging
- deterministic regression checks

## Non-goals in Current Phase

- automatic channel launch
- scoring-based automatic decisions
- backlog auto-generation
- production publishing logic changes
