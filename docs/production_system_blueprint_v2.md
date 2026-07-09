# Production System Blueprint v2

## 1. Executive Overview

### Mission
Build and operate a resilient AI-driven media production system that can publish high-quality YouTube long-form and Shorts content across multiple channels with minimal manual intervention.

### Problems Solved
- End-to-end automation from topic/script generation to publish.
- Multi-channel operation with shared infrastructure.
- Safe production behavior under partial dependency failures.
- Observable output quality via telemetry and analytics snapshots.

### Production Principles
- Safety first: factual and operational gates before publish.
- Determinism where possible: replayable and testable flows.
- Fail-open for optional enrichments, fail-closed for critical correctness.
- Cost-aware operation: free-first defaults until revenue justifies premium.
- Backward compatibility: avoid breaking stable production paths.

## 2. Architecture Map

### A. Production Pipeline (Active Track)
Primary orchestrator: [src/pipeline.py](src/pipeline.py)

Main stages:
1. Content generation
2. Fact-check and optional regeneration
3. TTS generation
4. Media acquisition (clips/images/music)
5. Long-form render
6. Shorts render
7. Upload and publish actions
8. Snapshot and telemetry persistence

### B. Scheduler Layer
- Production scheduler: [scheduler.py](scheduler.py)
- Secondary/legacy scheduler surface: [src/scheduler.py](src/scheduler.py)

Target state:
- One canonical scheduler entrypoint.
- Explicit role split between production scheduling and passive research scheduling.

### C. Passive Research Track
Architectural baseline: [docs/architecture.md](docs/architecture.md)

Capabilities:
- Append-only event collection
- Replay/backtest-ready historical analysis
- Deterministic report generation goals (see [docs/v0.2.0_planning.md](docs/v0.2.0_planning.md))

### D. Analytics and Feedback
Core output signals:
- Channel performance snapshots
- Thumbnail and render metadata
- Pipeline stage telemetry

Purpose:
- Close the loop between production choices and outcomes (CTR, watch-time proxies, trend fit).

## 3. Dependency Matrix

### Mandatory for Current Production Path
1. Anthropic API (content generation)
2. YouTube Data API (upload and metadata operations)
3. Core media libraries in [requirements.txt](requirements.txt)

### Optional (Free-First Mode Compatible)
1. Pexels API (free media source, quota-bound)
2. Edge TTS fallback (free)
3. Local music library and synthetic/internal tracks

### Optional Premium Services
1. Azure TTS
2. ElevenLabs TTS
3. Storyblocks media
4. DALL-E image generation
5. HeyGen avatar generation

### Fallback Chains
- TTS: Azure -> ElevenLabs -> Edge (fallback behavior controlled in [src/tts_engine.py](src/tts_engine.py)).
- Media: Premium source -> Pexels -> local/static fallback (behavior split across [src/image_fetcher.py](src/image_fetcher.py) and [src/premium_services.py](src/premium_services.py)).
- Music: selector policy and ducking pipeline metadata (see music layer integration in pipeline).

### Cost State Policy
Default operating mode is free-first until KPI thresholds are met (revenue/retention reliability), then premium dependencies are enabled selectively per channel.

## 4. Production Pipeline Specification

### Stage 1: Content Generation
- Generate title/script/description/thumbnail intent.
- Apply channel DNA and language constraints.

### Stage 2: Fact-Check and Regeneration
- Validate factual freshness and risky claims.
- If invalid, regenerate with stricter constraints.
- Block publish for unresolved critical factual risk.

### Stage 3: TTS
- Produce narration audio.
- Persist timing metadata where available for subtitle alignment.

### Stage 4: Visual Acquisition
- Acquire topic-aligned video clips and images.
- Keep non-blocking behavior for optional premium failures.

### Stage 5: Render (Long + Shorts)
- Assemble visual timeline, subtitles, transitions.
- Apply music selection and ducking mix.
- Produce thumbnail with safety constraints.

### Stage 6: Pre-Upload Safety Gates
- File integrity checks
- Fact-check pass confirmation
- API reachability and quota sanity
- Disk/runtime health minimums

### Stage 7: Upload & Publish
- Upload video and optional thumbnail.
- Apply scheduling strategy.
- Attempt comments/extra actions only when quota and permissions allow.

### Stage 8: Telemetry & Snapshot
- Persist stage outcomes, durations, and failure reasons.
- Persist channel-level snapshot continuity even on partial failures.

## 5. Research Platform Specification

### Collectors
- Contract-based collectors with source/schema/observed_at/raw envelope.
- Fail-open per source.

### Event Store
- Append-only JSONL storage.
- Clear schema versioning and deterministic replay windows.

### Replay Engine
- Deterministic read/filter pipeline.
- Supports reproducible backtesting and debugging.

### Output Layer
- Daily JSON + Markdown reports.
- Deterministic Top-N opportunities with explicit tie-break logic.

## 6. Safety Gates

### Upload-Blocking Gates (Fail-Closed)
1. Fatal render artifact or missing output
2. Critical factual risk unresolved
3. Required credentials unavailable

### Non-Blocking Gates (Fail-Open with Degradation)
1. Premium media source unavailable
2. Optional enhancement service timeout
3. Non-critical analytics write failures

### Operational Health Gates
1. API health and quota checks
2. Disk space threshold checks
3. Rate-limit awareness and backoff policies
4. End-to-end telemetry envelope completeness

## 7. Analytics and Feedback Loop

### Core Metrics
1. CTR
2. Average view duration / watch-time proxy
3. Thumbnail performance by variant archetype
4. Upload success/failure profile
5. Topic-cluster performance drift

### Decision Loop
1. Collect metrics into snapshots
2. Compare against baseline by channel
3. Trigger policy updates (thumbnail style, topic mix, cadence)
4. Re-run with guardrails and monitor deltas

## 8. Technical Debt Register

### Priority Debt Items
1. Duplicate scheduler surfaces ([scheduler.py](scheduler.py), [src/scheduler.py](src/scheduler.py)).
2. Potential overlap between legacy and pro creator paths.
3. Growing config sprawl across environment and runtime branches.
4. Mixed policy defaults requiring stronger single-source policy ownership.

### Planned Refactors
1. Canonical scheduler consolidation.
2. Production path hard-freeze contract (single approved render path).
3. Unified dependency policy object (free/premium gating).
4. Formalized preflight and postflight check modules.

## 9. Roadmap

### v0.2
- Stabilize passive research determinism.
- Complete provider abstraction and validation hardening.
- Keep production behavior stable while improving observability.

### v0.3
- Introduce explicit policy-driven optimization loop.
- Add stronger cross-channel allocation and scheduling intelligence.
- Expand safety automation and canary publish strategy.

### Phase 2: Audience Performance Engine
- Execution plan reference: [docs/phase2_audience_performance_engine.md](docs/phase2_audience_performance_engine.md)
- KPI contract reference: [docs/kpi_contract_phase2.md](docs/kpi_contract_phase2.md)
- Experiment registry schema reference: [docs/experiment_registry_schema.md](docs/experiment_registry_schema.md)
- Delivery rule: optimization work must run through experiment framework first, then thumbnail/audio/analytics intelligence workstreams.

### v1.0
- Full operating-system posture:
  - deterministic production + deterministic research replay
  - codified governance gates
  - cost-aware autonomous optimization with operator override

## 10. Backlog Prioritization Model

Each backlog item must include:
1. Expected impact (reach/revenue/reliability)
2. Risk (production, compliance, factual, operational)
3. Effort estimate (S/M/L + confidence)
4. Rollback plan
5. Test strategy and observability hooks

### Initial Priority Queue (Proposed)
1. Scheduler consolidation
- Impact: High
- Risk: Medium
- Effort: M

2. Unified preflight gate module
- Impact: High
- Risk: Low
- Effort: M

3. Policy ownership hardening (free-first vs premium)
- Impact: High
- Risk: Low
- Effort: S

4. Thumbnail strategy experiment framework
- Impact: Medium-High
- Risk: Low
- Effort: M

5. Research-to-production handoff contract
- Impact: Medium
- Risk: Medium
- Effort: M/L

## 11. Governance Artifacts

Resmi dokümantasyon kaynakları:
1. Architecture Blueprint: [docs/production_system_blueprint_v2.md](docs/production_system_blueprint_v2.md)
2. Architecture Audit: [docs/architecture_audit_2026-07-09.md](docs/architecture_audit_2026-07-09.md)
3. ADR Decision Log klasörü: [docs/adr](docs/adr)
4. ADR indeksi: [docs/adr/README.md](docs/adr/README.md)
5. Production Readiness Checklist: [docs/production_readiness_checklist.md](docs/production_readiness_checklist.md)
6. Phase 2 Execution Plan: [docs/phase2_audience_performance_engine.md](docs/phase2_audience_performance_engine.md)
7. Phase 2 KPI Contract: [docs/kpi_contract_phase2.md](docs/kpi_contract_phase2.md)
8. Experiment Registry Schema: [docs/experiment_registry_schema.md](docs/experiment_registry_schema.md)

Tek yönetim modeli (zorunlu akış):
1. Blueprint: sistem tanımı, kapsam ve guardrail çerçevesi.
2. Audit: mevcut durum, satır-seviye riskler ve önceliklendirme.
3. ADR: önemli teknik/mimari kararların gerekçeli kayıt altına alınması.
4. Checklist: release öncesi go/no-go operasyon kapısı.
5. Roadmap: açık riskler, teknik borçlar ve bir sonraki geliştirme dalgası.

Bu akış, feature geliştirmeden önce ve release kararlarından önce birlikte işletilmelidir.

## Governance Rule
Before any new feature implementation:
1. Update this blueprint section(s) first.
2. Mark affected architecture components.
3. Define safety and rollback implications.
4. Validate alignment with Audit + ADR + Production Readiness Checklist.
5. Only then open implementation PR.
