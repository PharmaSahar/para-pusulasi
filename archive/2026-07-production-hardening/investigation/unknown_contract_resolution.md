# Unknown Contract Resolution

Date: 2026-07-12
Scope: Resolve the 2 UNKNOWN tests previously listed in `artifacts/latest/production_contract_validation.md`.
Candidate under validation: `adc021b7842f1fb60ec289687128d539637745e8`
Current workspace head: `d51e31578e3f3bd18674441f2f7545a2dce2dd05`

## 1) Exact UNKNOWN Tests Investigated

### A. `tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block`
- File and line: `tests/test_scheduler_topic_domain_guard.py:52`
- Stated contract: topic-domain blocked path must create a quarantined queue entry with topic-domain guard code.
- Prior UNKNOWN reason: candidate runtime showed missing `demo_channel` queue key; quarantine existed only for upload-precheck-blocked result branch.
- Missing evidence that blocked prior classification: no before/after proof separating fixture artifact from real production exception shape.

### B. `tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried`
- File and line: `tests/test_scheduler_topic_domain_guard.py:75`
- Stated contract: topic-domain blocked path should not retry pipeline invocation.
- Prior UNKNOWN reason: candidate runtime showed `calls["pipeline"] == 3` for raised `RuntimeError("topic_domain_blocked:...")`.
- Missing evidence that blocked prior classification: no proof whether production exception shape uses retry-skip markers that the fixture omitted.

## 2) Independent Reproduction (Isolated, One Test Per Run)

Flags used for each run:
- `-vv --tb=long -W error -s`
- isolated temp runtime roots
- isolated scheduler/log/telemetry/queue env paths
- `YOUTUBE_CLIENT_ID/YOUTUBE_CLIENT_SECRET/ANTHROPIC_API_KEY/ELEVENLABS_API_KEY/TELEGRAM_BOT_TOKEN=preprod-disabled`
- `SCHEDULE_ENABLED=false`
- no live upload

Raw outputs:
- `artifacts/latest/unknown_contract_evidence/test_scheduler_quarantines_topic_domain_block.out`
- `artifacts/latest/unknown_contract_evidence/test_scheduler_topic_domain_block_is_not_retried.out`
- metadata:
  - `artifacts/latest/unknown_contract_evidence/test_scheduler_quarantines_topic_domain_block.meta.json`
  - `artifacts/latest/unknown_contract_evidence/test_scheduler_topic_domain_block_is_not_retried.meta.json`

Observed (current head): both pass in isolation.

## 3) Fixture Validity Analysis

### A. Quarantine test fixture validity
- Influencing fixture fields:
  - script/video/thumbnail/manifest: not provided (scheduler-level unit test bypasses artifact pipeline outputs).
  - channel ID/topic-domain metadata: provided (`demo_channel`, niche `saglik`, error text includes `topic_domain_blocked`).
  - exception type: plain `RuntimeError` (not `TopicDomainBlockedError`).
  - retry marker/quarantine attrs: absent in test exception.
- Validity classification: `VALID PRODUCTION SCENARIO` for domain-token classification only after classifier hardening; `INCOMPLETE` for full production exception metadata.

### B. No-retry test fixture validity
- Influencing fixture fields:
  - script/video/thumbnail/manifest: not provided (N/A for scheduler-level unit assertion).
  - exception type: plain `RuntimeError`.
  - retry marker `_skip_scheduler_pipeline_retry`: absent.
- Production contract implication:
  - pipeline sets `_skip_scheduler_pipeline_retry=True` on `TopicDomainBlockedError` before scheduler sees exception.
  - fixture omission changes branch selection at candidate.
- Validity classification: `INVALID / LEGACY FIXTURE` for candidate no-retry assertion.

## 4) Authoritative Contract Evidence (Git + Code)

### Original contract introduction
- Commit: `631eb704d0af9a057cca6f737855f0d446da5f91`
- Author: Sahar
- Date: 2026-07-11 19:28:57 +0300
- Subject: `fix: block cross-channel and invalid artifact uploads`
- Evidence files:
  - `artifacts/latest/unknown_contract_evidence/commit_631eb704_meta.txt`
  - `artifacts/latest/unknown_contract_evidence/commit_631eb704_scheduler_topic_guard.patch`
- Same commit also added the two scheduler topic-domain tests.

### Current contract hardening / superseding behavior
- Commit: `72b4bb208a84c93eff5a471e142853e01a5c28a4`
- Author: Sahar
- Date: 2026-07-12 06:51:52 +0300
- Subject: `fix: quarantine terminal domain blocks and isolate preprod outputs`
- Evidence files:
  - `artifacts/latest/unknown_contract_evidence/commit_72b4bb2_meta.txt`
  - `artifacts/latest/unknown_contract_evidence/commit_72b4bb2_scheduler_topic_guard.patch`
- Key diff/code references (current file):
  - non-retryable domain token set and classifier: `scheduler.py:168`, `scheduler.py:533`
  - non-retryable quarantine branch in retry loop: `scheduler.py:896`
  - quarantine entry upsert function: `scheduler.py:599`
  - exception handler quarantine invocation: `scheduler.py:1087`

### Production-side exception shaping evidence
- Topic-domain source exception class and messages:
  - `src/content_generator.py:132`, `src/content_generator.py:1082`, `src/content_generator.py:1193`
- Pipeline enriches topic-domain exception with retry-skip and quarantine metadata:
  - `src/pipeline.py:872-885`

## 5) Baseline vs Current (Deterministic Before/After)

Comparison artifact:
- `artifacts/latest/unknown_contract_before_after.json`

Before (candidate): `adc021b7842f1fb60ec289687128d539637745e8`
After (current): `d51e31578e3f3bd18674441f2f7545a2dce2dd05`

Raw before/after runs:
- `artifacts/latest/unknown_contract_evidence/worktree_runs_v2/before_tests_test_scheduler_topic_domain_guard.py__test_scheduler_quarantines_topic_domain_block.out`
- `artifacts/latest/unknown_contract_evidence/worktree_runs_v2/before_tests_test_scheduler_topic_domain_guard.py__test_scheduler_topic_domain_block_is_not_retried.out`
- `artifacts/latest/unknown_contract_evidence/worktree_runs_v2/after_tests_test_scheduler_topic_domain_guard.py__test_scheduler_quarantines_topic_domain_block.out`
- `artifacts/latest/unknown_contract_evidence/worktree_runs_v2/after_tests_test_scheduler_topic_domain_guard.py__test_scheduler_topic_domain_block_is_not_retried.out`

Findings:
- Candidate:
  - quarantine test fails: `KeyError: 'demo_channel'`
  - no-retry test fails: `assert 3 == 1`
- Current:
  - both tests pass

Production-like exception probe (read-only, no upload):
- `artifacts/latest/unknown_contract_evidence/domain_exception_probe.py`
- before output: `artifacts/latest/unknown_contract_evidence/before_production_like_exception_probe.out`
- after output: `artifacts/latest/unknown_contract_evidence/after_production_like_exception_probe.out`

Probe result:
- Candidate: `calls=1` but queue remains `{}` (no quarantine entry).
- Current: `calls=1` and queue contains quarantined entry with guard and identity fields.

## 6) Real Production Compatibility Check (Read-only)

- Current production topic-domain path emits `TopicDomainBlockedError` and pipeline attaches:
  - `_skip_scheduler_pipeline_retry`
  - `_quarantine_reason`
  - `_guard_reason_codes`
  - run/content/topic/domain metadata
- Scheduler quarantine payload currently stores:
  - `channel_id`, `run_id`, `content_id`, `topic`, `expected_niche`, `detected_domain`, `guard_reason_codes`, `prevent_upload`, `prevent_shorts_upload`.
- Conclusion:
  - Quarantine test contract aligns with current production artifact/quarantine schema.
  - No-retry test fixture at candidate used a legacy exception shape that omitted production retry marker semantics.

## 7) Final Classification (No UNKNOWN Remaining)

### Test A
- Test: `tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block`
- Original contract: topic-domain blocked exception should materialize as quarantined queue state.
- Current authoritative contract: non-retryable domain blocks are quarantined with guard metadata.
- Fixture validity: valid enough to represent domain-block signal; verified with production-like probe as well.
- Observed behavior:
  - candidate: no quarantine entry
  - current: quarantine entry created
- Git evidence: fix introduced in `72b4bb2` with classifier + quarantine upsert path.
- Runtime evidence: before/after isolated runs + production-like probe outputs.
- Classification: `PRODUCTION REGRESSION` (for candidate scope).
- Recommended repair target: scheduler exception path for terminal topic-domain blocks.
- Estimated LOC: 20-60 (already reflected by `72b4bb2` scale).

### Test B
- Test: `tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried`
- Original contract: topic-domain blocked should not retry.
- Current authoritative contract: no-retry is guaranteed for production topic-domain exceptions via retry-skip marker and current classifier.
- Fixture validity: `INVALID / LEGACY FIXTURE` at candidate for no-retry assertion (missing retry marker metadata).
- Observed behavior:
  - candidate test fixture retries 3x
  - candidate production-like probe exception does not retry (`calls=1`)
- Git evidence: marker-based no-retry path existed; token-based classifier later widened coverage.
- Runtime evidence: isolated failing test + production-like probe.
- Classification: `OUTDATED TEST`.
- Recommended repair target: update fixture to production exception shape or explicit classifier contract.
- Estimated LOC: 8-20.

## 8) Updated Totals and Recommendation

- total original failures: 9
- outdated tests: 8
- production regressions: 1
- unresolved tests: 0

GO / NO-GO: `NO-GO`
- Reason: one validated production regression remains in candidate scope (`test_scheduler_quarantines_topic_domain_block` contract).
