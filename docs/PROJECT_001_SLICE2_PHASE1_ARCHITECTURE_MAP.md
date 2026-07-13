# PROJECT 001 Slice 2 - Phase 1 Architecture Map

Date: 2026-07-13
Scope: local repository only (`/Users/klara/Projects/parapusulasi`)

## 1) Canonical Channel Registry and ID Mapping

Canonical source of truth:
- `channels/channel_registry.json`
- Loader: `src/channel_manager.py` (`load_registry`, `list_channels`, `get_channel`)

Manual display-name to canonical-id mapping (unambiguous in current registry):
- Para Pusulasi -> `para_pusulasi`
- Kariyer Pusulasi -> `kariyer_pusulasi`
- Girisim Okulu -> `girisim_okulu`
- Borsa Akademi -> `borsa_akademi`
- Kripto Rehber -> `kripto_rehber`

Notes:
- For `girisim_okulu`, canonical ID is the JSON key; entry does not explicitly repeat `channel_id` field.
- Active + pending channels are mixed in the same registry, distinguished by `status` (for example `active`, `pending_oauth`).

## 2) Scheduler Channel-Loading Path

Primary scheduler entrypoint:
- `scheduler.py`

Relevant path:
- `get_ready_channels()` -> imports `list_channels` and `get_channel` from `src/channel_manager.py`
- Ready criteria: token file exists at `cfg.token_path`
- Per-channel pipeline execution: `render_and_schedule(channel_id)` -> `run_full_pipeline(channel_cfg=cfg, ...)`

Queue and gating signals in scheduler:
- Queue persistence: `load_queue`, `update_queue`, `save_queue`
- Existing block flags on quarantined queue entries:
  - `prevent_upload`
  - `prevent_shorts_upload`

## 3) Upload Pipeline

Main pipeline:
- `src/pipeline.py` -> `run_full_pipeline(...)`

Upload phases in pipeline:
- Main upload stage uses `YouTubeUploader.upload_video(...)`
- Shorts render stage (`shorts_render`) creates short asset via `src/shorts_creator.py`
- Shorts upload stage (`shorts_upload`) uploads short via `YouTubeUploader.upload_video(...)`

Uploader implementation:
- `src/youtube_uploader.py`

## 4) Normal Video Upload Path

Main path:
- `src/pipeline.py` ADIM 4 uploads main video through `YouTubeUploader.upload_video(...)`

Details:
- Description is normalized and chapter-safe via `_build_upload_description(...)`
- Upload idempotency is handled in pipeline using production quality platform helpers
- Upload precheck (`src/upload_precheck.py`) may block upload before API call

## 5) Shorts Upload Path

Render:
- `src/pipeline.py` ADIM 3.5 -> `ShortsCreator.create_short(...)`

Upload:
- `src/pipeline.py` ADIM 4.5 -> second `YouTubeUploader.upload_video(...)` call with short metadata

Current behavior:
- Shorts upload is skipped if main upload fails or is blocked by precheck
- No channel capability registry currently controls shorts eligibility

## 6) Thumbnail Generation and Upload Path

Generation:
- Main thumbnail produced in `src/pipeline.py` (video creator `create_thumbnail`)
- Shorts thumbnail optionally regenerated for short-specific diversity

Upload:
- `src/youtube_uploader.py` -> `_upload_thumbnail(...)`

Existing eligibility-like logic:
- Thumbnail permission cache: `logs/thumbnail_permission_cache.json`
- On thumbnail 403, uploader disables thumbnail attempts for that channel/session and caches state
- This is operational/API-permission driven, not a channel capability tier model

## 7) Description and External Link Handling

Description build:
- `src/youtube_uploader.py` -> `_build_upload_description(...)`

External links:
- `src/monetization.py` contains affiliate/link helpers (`get_description_with_affiliate`)
- Current pipeline/uploader path does not centrally enforce channel-level external-link capability gates

## 8) Video Duration Controls

Shorts duration:
- `src/shorts_creator.py` enforces short duration cap with `SHORT_DURATION = 58`

Long-form threshold logic:
- No centralized channel capability gate currently enforces `>15 minutes` eligibility.
- `src/youtube_uploader.py` reads duration for chapter generation quality logic, not eligibility gating.

## 9) Live Streaming Related Code

Observed live-related code:
- `scheduler.py` live analytics refresh controls (`LIVE_COLLECTOR_ENABLED`, `YOUTUBE_ANALYTICS_API_GO`, rollout approval)

Not observed:
- No explicit live-stream creation/upload workflow in current pipeline
- No existing live-stream eligibility gate tied to channel verification tiers

## 10) Daily Upload-Limit Handling

Current handling:
- No explicit per-channel capability-tier daily limit manager found
- Quota-aware comments in uploader (`YouTube API units`) and error classification exist
- Scheduler queue + timing determines operational cadence, not tier-aware hard limits

## 11) Feature Flags and Config Mechanisms

Examples of existing gates:
- `FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED`
- `PRODUCTION_QUALITY_PLATFORM_ENABLED`
- `CONTENT_QUALITY_GATE_ENABLED`
- `UPLOAD_PRECHECK_ENABLED`
- `LIVE_COLLECTOR_ENABLED`, `YOUTUBE_ANALYTICS_API_GO`, `LIVE_COLLECTOR_ROLLOUT_APPROVED`

Pattern:
- Fail-open telemetry helpers
- Explicit env-flag control for runtime behavior

## 12) Existing Eligibility/Verification/Quota/Capability Logic

Existing partial eligibility signals:
- Thumbnail upload permission fallback cache after 403
- Upload precheck ownership and domain checks
- Quota/auth error classification and retries

Missing foundation (to be added in Slice 2 Phase 1):
- Central channel capability registry with typed states
- Central feature-to-capability mapping
- Provider abstraction and deterministic resolution order

## 13) Integration Constraints for Slice 2 Phase 1

Must remain true for this phase:
- Backward compatible defaults
- Safe fail behavior on missing/invalid capability data
- No deployment/restart/production mutation
- Foundation only; no metadata optimization implementation
