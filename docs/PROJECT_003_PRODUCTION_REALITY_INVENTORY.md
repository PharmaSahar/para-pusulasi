# PROJECT 003 — Production Reality Inventory

## Scope

Read-only production inventory based on live host evidence, service state, deployed Git state, runtime logs, and repository-side operational documentation.

## Live Host Evidence

- Hostname: `ubuntu-4gb-nbg1-1`
- UTC timestamp observed on host: `2026-07-15T12:50:13Z`
- Service: `parapusulasi.service`
- Service status: active (running)
- Main PID: `210419`
- Scheduler command: `/opt/parapusulasi-current/venv/bin/python /opt/parapusulasi-current/scheduler.py`
- Deployed root: `/opt/parapusulasi/releases/68529058e386661d19eaa2dfe510523d7c6cd47a`
- Active symlink: `/opt/parapusulasi-current`
- Current release SHA: `68529058e386661d19eaa2dfe510523d7c6cd47a`
- Repository checkout SHA under `/opt/parapusulasi`: `9de59809f8df6b2f020f9548a1346e781e2b4a8d`
- Repository checkout branch under `/opt/parapusulasi`: `build_identity_fix`

## SHA Split Classification

- ACTIVE_RUNTIME_SHA: `68529058e386661d19eaa2dfe510523d7c6cd47a`
- ACTIVE_RELEASE_SHA: `68529058e386661d19eaa2dfe510523d7c6cd47a`
- CHECKED_OUT_REPOSITORY_SHA: `9de59809f8df6b2f020f9548a1346e781e2b4a8d`
- LOCAL_MASTER_SHA: `836dfe3fbe15faadfec40e3acd3b40799a5ad37b`
- ORIGIN_MASTER_SHA: `836dfe3fbe15faadfec40e3acd3b40799a5ad37b`
- Classification: EXPECTED_RELEASE_LAYOUT

The running service executes the symlinked release tree, not the host checkout.

## Runtime Process Inventory

- Scheduler process: present and running
- Uploader process: not observed in the SSH inventory snapshot
- Worker processes: ffmpeg child process observed under the scheduler service cgroup
- Cron/timer evidence: no separate cron/timer inventory was captured in this read-only probe

## Queue Evidence

Observed queue counts from `/opt/parapusulasi/output/queue/channel_queue.json`:
- para_pusulasi: 5
- borsa_akademi: 3
- kripto_rehber: 5
- kariyer_pusulasi: 8
- girisim_okulu: 9
- saglik_pusulasi: 2
- teknoloji_pusulasi: 7
- egitim_rehberi: 5
- gayrimenkul_tv: 1

## Repository-Side Production Baseline

- Repository baseline SHA for published Sprint 9 history: `836dfe3fbe15faadfec40e3acd3b40799a5ad37b`
- Production baseline document SHA reference: `c732427367d782f56c335e52dd063deaa8db3e0d`
- Current live release SHA differs from repository HEAD and from the published Sprint 9 commit.

## Module Reality Classification

### Old automation components
- [src/scheduler.py](src/scheduler.py): CALLED_IN_PRODUCTION
- [src/youtube_uploader.py](src/youtube_uploader.py): PRESENT_IN_PRODUCTION / imported by runtime code paths, but no separate uploader process was observed in this inventory snapshot
- [src/youtube_analytics.py](src/youtube_analytics.py): PRESENT_IN_PRODUCTION as a governed capability, but live analytics collector remains disabled until YouTube Analytics API go-decision
- [deploy/setup_vps.sh](deploy/setup_vps.sh): DORMANT in production runtime, operational only
- [deploy/transfer.sh](deploy/transfer.sh): DORMANT in production runtime, operational only
- [deploy/single_root_cutover.sh](deploy/single_root_cutover.sh): DORMANT in production runtime, operational only

### Project 002 components
- [src/production_readiness.py](src/production_readiness.py): PRESENT_IN_PRODUCTION as a health-check/support module
- [src/production_quality_platform.py](src/production_quality_platform.py): PRESENT_IN_PRODUCTION as a runtime support module
- [src/unresolved_analytics_recovery.py](src/unresolved_analytics_recovery.py): LOCAL_ONLY / audit and recovery support, not proven live in this probe
- [src/historical_lineage_recovery.py](src/historical_lineage_recovery.py): LOCAL_ONLY / audit and recovery support, not proven live in this probe
- [src/fact_check_audit.py](src/fact_check_audit.py): PRESENT_IN_PRODUCTION as audit support if invoked by runtime, but not directly observed in the SSH command snapshot

### Project 003 Sprint 1–9 modules
- [src/run_registry_audit.py](src/run_registry_audit.py): ADVISORY_ONLY / imports the registry stores for manual audits, not on the live runtime call path
- [src/model_registry.py](src/model_registry.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [src/model_registry_projection.py](src/model_registry_projection.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [src/policy_registry.py](src/policy_registry.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [src/policy_registry_projection.py](src/policy_registry_projection.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [src/prompt_governance_registry.py](src/prompt_governance_registry.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [src/prompt_governance_registry_projection.py](src/prompt_governance_registry_projection.py): PRESENT_NOT_IMPORTED / repository module with no runtime import observed
- [docs/PROJECT_003_SPRINT9_REGISTRY_GOVERNANCE.md](docs/PROJECT_003_SPRINT9_REGISTRY_GOVERNANCE.md): local documentation only
- [docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md](docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md): local documentation only

### Runtime call-graph summary
- Scheduler entry point: [src/scheduler.py](src/scheduler.py) calls [src/pipeline.py](src/pipeline.py) via `run_full_pipeline()`.
- Uploader entry point: [src/youtube_uploader.py](src/youtube_uploader.py) is imported by the pipeline.
- Queue loader: [src/channel_manager.py](src/channel_manager.py) and pipeline config load the active channel settings; the live queue state is read from `/opt/parapusulasi/output/queue/channel_queue.json` on the host.
- Rendering pipeline: [src/pipeline.py](src/pipeline.py), [src/video_creator_pro.py](src/video_creator_pro.py), and ffmpeg child processes observed under the service cgroup.
- Metadata generation: [src/content_generator.py](src/content_generator.py), [src/metadata_repair.py](src/metadata_repair.py), and [src/channel_dna.py](src/channel_dna.py).
- Title generation: [src/content_generator.py](src/content_generator.py) and [src/quality_scoring.py](src/quality_scoring.py).
- Thumbnail generation: [src/thumbnail_candidate_generator.py](src/thumbnail_candidate_generator.py), [src/thumbnail_experiment.py](src/thumbnail_experiment.py), [src/thumbnail_selection_policy.py](src/thumbnail_selection_policy.py), and [src/visual_diversity.py](src/visual_diversity.py).
- Shorts path: [src/shorts_creator.py](src/shorts_creator.py) and [src/shadow_generation_planning.py](src/shadow_generation_planning.py).
- Long-form path: [src/video_creator.py](src/video_creator.py) and [src/video_creator_pro.py](src/video_creator_pro.py).
- Analytics collector: [src/pipeline.py](src/pipeline.py) resolves the live collector gate; [src/analytics_collector.py](src/analytics_collector.py) and [src/youtube_analytics.py](src/youtube_analytics.py) provide the read path, but live collection remains disabled.
- Dashboard writer: [src/production_quality_platform.py](src/production_quality_platform.py) writes production dashboard/evidence outputs.

## Live Versus Dormant Summary

### Live in production
- Scheduler service and its associated runtime pipeline
- Content generation/rendering pipeline stages observed in the scheduler log tail
- Existing channel queue state and runtime render output paths
- Production host with active systemd service and release symlink

### Present but dormant or disabled
- Live analytics collector is explicitly disabled until YouTube Analytics API go-decision
- Documentation-only deployment scripts
- Repository-only registry governance modules

## Analytics Root Cause

- Root-cause classification: CONFIG_DISABLED
- Evidence: [src/pipeline.py](src/pipeline.py) returns `no_go_api_not_enabled` when `YOUTUBE_ANALYTICS_API_GO` is false or absent.
- Evidence: the same pipeline branch still forces `analytics_warning` with message `Live analytics collector disabled until YouTube Analytics API go-decision.`
- Evidence: the live host telemetry captured `analytics_live_status: no_go_api_not_enabled` and `live_collector_enabled: false`.
- Evidence: no secret-bearing token values were printed; only presence and path topology were inspected.

## Read-Only Smoke Availability

- Status: ANALYTICS_SMOKE_NOT_AVAILABLE
- Reason: no existing governed command was found that performs a minimal read-only analytics smoke without also invoking the interactive OAuth/token path or mutating scheduler state.
- Smallest follow-up operational task: add a dedicated read-only smoke wrapper around `collect_analytics_rows()` or `fetch_recent_video_analytics()` that uses one channel, a fixed date window, and a clearly read-only credential check.

### Never proven live in this inventory
- Sprint 9 registry modules as runtime components
- Emergency roadmap and audit documents
- Documentation commits themselves

## Production Drift

- Production release SHA differs from the repository HEAD published for Sprint 9.
- The live service is executing the release tree under `/opt/parapusulasi-current`, while the host checkout under `/opt/parapusulasi` sits on a different branch and SHA.
- Runtime root is a release directory under `/opt/parapusulasi/releases/` with a symlinked current root.

## Security and Evidence Notes

- No secret values are recorded here.
- No YouTube write operations were performed.
- No production restart or deploy was executed during this inventory.
