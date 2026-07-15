# EMERGENCY CHANNEL RECOVERY PLAN 20260715

## Scope

This plan is a governed recovery draft. It does not execute mutations and does not require Sprint 10 completion.

## Immediate Safe Actions

### 1. Preserve live scheduler behavior while pausing new assumptions
- Channel: all active channels
- Affected videos/jobs: current queue items across all channels
- Evidence: live host shows active scheduler service, populated queue, and incomplete analytics evidence
- Expected benefit: prevents misdiagnosis-driven changes
- Risk: none if limited to observation
- Rollback: not applicable
- Owner: operations lead
- Approval required: yes, for any later mutation
- Measurement window: next 24-48 hours
- Success metric: no new unverified changes introduced

### 2. Verify current runtime SHA against repository publication history
- Channel: all active channels
- Affected videos/jobs: all future jobs until drift is understood
- Evidence: live host SHA differs from repository publication SHA
- Expected benefit: establishes whether production is on a shadow, older, or alternate branch
- Risk: none
- Rollback: not applicable
- Owner: release steward
- Approval required: no for read-only verification
- Measurement window: immediate
- Success metric: runtime drift classified

### 3. Quarantine any contaminated queue item if evidence appears
- Channel: channel-specific
- Affected videos/jobs: only the flagged job(s)
- Evidence: would require item-level runtime confirmation not yet captured
- Expected benefit: prevents propagation of wrong-domain or wrong-channel outputs
- Risk: false positive if acted on without evidence
- Rollback: requeue after human review
- Owner: operator
- Approval required: yes
- Measurement window: per incident
- Success metric: contaminated item isolated

### 4. Add a governed read-only analytics smoke
- Channel: a single representative channel only
- Affected videos/jobs: none
- Evidence: analytics live collection is currently disabled by config, so the next smallest recovery task is to create a read-only smoke command rather than mutate production behavior
- Expected benefit: establishes whether the analytics path is operational once the go decision exists
- Risk: none if implemented as read-only
- Rollback: not applicable
- Owner: tooling maintainer
- Approval required: yes, for the implementation task only
- Measurement window: one snapshot
- Success metric: a minimal read-only analytics result can be captured without changing any production state

## Human-Review Actions

### A. Packaging consistency review
- Channel: all active channels
- Affected videos/jobs: highest-volume recent outputs
- Evidence: long-form-heavy dashboard window, live scheduler processing, and topic/domain policies
- Expected benefit: reduce CTR fatigue
- Risk: over-correcting without analytics
- Rollback: restore previous packaging set
- Owner: channel owner
- Approval required: yes
- Measurement window: 7/28 days
- Success metric: CTR and retention improve without contamination

### B. Topic repetition review
- Channel: channels with repeated topic clusters
- Affected videos/jobs: repeated-topic content families
- Evidence: current queue distribution and scheduler output patterns
- Expected benefit: reduce audience fatigue
- Risk: changing too much at once
- Rollback: revert to prior topic mix
- Owner: content strategist
- Approval required: yes
- Measurement window: 2-4 weeks
- Success metric: browse and suggested traffic stabilize or improve

### C. Upload cadence review
- Channel: all active channels
- Affected videos/jobs: future scheduled uploads
- Evidence: queue counts across active channels
- Expected benefit: align frequency with audience tolerance
- Risk: lowering output too much
- Rollback: restore prior schedule
- Owner: operations + channel lead
- Approval required: yes
- Measurement window: 2-4 weeks
- Success metric: retention does not worsen while CTR rises

## Experiment-Required Actions

### A. Intro/hook redesign
- Channel: per-channel
- Affected videos/jobs: experimental set only
- Evidence: insufficient live retention evidence
- Expected benefit: improve 30-second retention
- Risk: content quality regression
- Rollback: restore prior intro template
- Owner: content experiment owner
- Approval required: yes
- Measurement window: 2-4 weeks
- Success metric: retention curve improves

### B. Thumbnail language redesign
- Channel: per-channel
- Affected videos/jobs: experimental set only
- Evidence: packaging fatigue suspected, but not confirmed
- Expected benefit: improve CTR
- Risk: mismatch with brand identity
- Rollback: revert thumbnail template
- Owner: design reviewer
- Approval required: yes
- Measurement window: 1-2 weeks
- Success metric: CTR improves without audience confusion

### C. Long-form / Shorts mix adjustment
- Channel: per-channel
- Affected videos/jobs: schedule cohort only
- Evidence: current dashboard snapshot shows zero Shorts in the captured window
- Expected benefit: diversify audience reach
- Risk: reduced long-form efficiency
- Rollback: restore previous mix
- Owner: channel lead
- Approval required: yes
- Measurement window: 2-4 weeks
- Success metric: total watch time and view stability improve

## Smallest Safe Emergency Next Task

- Build or expose a read-only analytics smoke command for one channel and one small date window.
- Do not connect it to recurring jobs, uploads, or metadata mutation.
- Use it only to prove the analytics path once the configuration gate is opened.

## Rollback Principles

- Keep changes single-variable whenever possible.
- Use human review before any mutation.
- Record before/after evidence for each action.
- Never use a recovery plan as a shortcut to live automation.

## Notes

This recovery plan is intentionally separate from Sprint 10 and does not authorize any autonomous action.
