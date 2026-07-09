# ADR-003: Multi-Channel Architecture

## Status
Accepted

## Date
2026-07-09

## Context
The product operates multiple channels with distinct audience DNA, visual identity, and scheduling patterns. A single global content path would couple channel behavior and raise regression risk.

## Decision
Adopt a multi-channel architecture with shared core pipeline and channel-scoped configuration.

- Keep orchestration primitives shared (pipeline, scheduler, validation, telemetry).
- Keep channel behavior configurable (topic DNA, branding, publishing cadence, language/metadata).
- Prefer channel-scoped artifacts and state snapshots where practical.
- Enforce guardrails so one channel failure does not cascade into all channels.

## Consequences
- Faster expansion to new channels with lower implementation overhead.
- Better isolation of channel-specific regressions.
- Higher need for governance around shared vs channel-local changes.

## Non-goals
- Full microservice decomposition per channel.
- Real-time cross-channel dependency graph.

## Follow-ups
- Maintain clear boundaries in docs between global defaults and channel overrides.
- Add channel-level health and throughput visibility to operations review.
