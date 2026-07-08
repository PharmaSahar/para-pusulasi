# Autonomous Media Operating System

This repository is evolving from a single automation project into the operating
system of an autonomous media company.

Primary goal:
- maximize long-term enterprise value
- keep production stable and resilient
- increase autonomy gradually and safely

## Current State

Production foundations are active and treated as protected assets:
- multi-channel production
- prompt registry and channel DNA
- experiment metadata and quality scoring
- analytics join and shadow editor review
- render metrics, telemetry, and production health monitoring

These are not experimental and are not rewritten without production evidence.

## Research Platform (Passive)

The current roadmap focus is passive research infrastructure.

Implemented layers:
- collector contract with schema versioning
- append-only research event store
- passive collectors:
  - google trends
  - github trends
  - reddit trends
- one-shot research scheduler
- one-shot research runner CLI
- replay engine (line-by-line, fail-open)
- replay runner CLI
- deterministic replay coverage
- research regression CI workflow

All of the above are passive. They do not change production flow, scoring,
backlog generation, or publication behavior.

## Core Principles

- production stability first
- business value over engineering elegance
- metadata before automation
- one feature per patch
- small, reversible changes
- fail-open where appropriate
- no duplicate sources of truth

## Repository Pointers

- Passive scheduler: [src/research_scheduler.py](src/research_scheduler.py)
- Collector contract: [src/collector_contract.py](src/collector_contract.py)
- Replay engine: [src/research_replay.py](src/research_replay.py)
- One-shot replay CLI: [src/run_replay_once.py](src/run_replay_once.py)
- CI workflow: [.github/workflows/research-ci.yml](.github/workflows/research-ci.yml)

## Run Research Regression Locally

```bash
pytest -q \
  tests/test_collector_contract.py \
  tests/test_google_trends_collector.py \
  tests/test_github_trends_collector.py \
  tests/test_reddit_trends_collector.py \
  tests/test_research_scheduler.py \
  tests/test_research_pipeline_smoke.py \
  tests/test_research_db.py \
  tests/test_research_replay.py \
  tests/test_run_replay_once.py \
  tests/test_research_replay_determinism.py
```

## One-shot Commands

Run passive collectors once:

```bash
python -m src.run_research_once --query bitcoin --query startup --pretty
```

Replay stored events once:

```bash
python -m src.run_replay_once --research-root research --schema-version 1 --pretty
```

## Documentation

- [docs/architecture.md](docs/architecture.md)
- [docs/collector_contract.md](docs/collector_contract.md)
- [CHANGELOG.md](CHANGELOG.md)
