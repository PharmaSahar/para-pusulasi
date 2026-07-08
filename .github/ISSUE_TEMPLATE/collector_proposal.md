---
name: Collector proposal
about: Propose a new passive data collector
title: "[Collector] "
labels: [research, collector]
assignees: []
---

## Source

Data source name and endpoint(s).

## Why This Source

What signal does it add?

## Contract Mapping

How output will map to required fields:

- `schema_version` = 1
- `source` =
- `observed_at` =
- `raw` =

## Failure Handling

Describe fail-open behavior and fallback.

## Test Plan

List tests to add (contract, persistence, error path, scheduler integration if needed).

## Constraints Check

- [ ] No production publishing flow changes
- [ ] No scoring/ranking in production path
- [ ] No auto-backlog generation
- [ ] Passive research behavior preserved
