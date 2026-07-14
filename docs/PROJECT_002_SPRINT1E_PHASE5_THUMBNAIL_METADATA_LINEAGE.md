# PROJECT 002 Sprint 1E Phase 5 - Thumbnail Metadata Lineage Foundation

## Scope
This phase adds a deterministic thumbnail metadata lineage layer.

Safety properties:
- append-only JSONL only
- advisory-only
- default-off
- fail-open
- pipeline_output_changed=false
- no scheduler behavior change
- no uploader behavior change
- no CQGA behavior change
- no prompt generation change
- no existing analytics mutation

## Captured Fields
Each lineage row records:
- content_id
- run_id
- blueprint_id
- planning_id
- thumbnail_generation_id
- thumbnail_prompt_hash
- image_hash
- metadata_version
- creation_timestamp

Additional advisory fields:
- content_type
- variant_id
- thumbnail_path
- completeness_score
- missing_fields
- integrity_hash

## Deterministic Identity
The thumbnail generation identity is derived from exact stored keys only:
- content_id
- run_id
- content_type
- variant_id
- thumbnail_prompt_hash
- image_hash

No guessed joins are used.

## Storage
Append-only lineage log:
- logs/thumbnail_metadata_lineage.jsonl

Rows are duplicate-checked by deterministic lineage_id.

## Replay and Integrity
Replay reconstructs thumbnail generations by thumbnail_generation_id.
Integrity verification recomputes the protected payload hash and reports:
- row count
- malformed rows
- replay errors
- duplicate groups
- average completeness score

## Runtime Integration
Pipeline integration is gated by:
- THUMBNAIL_METADATA_LINEAGE_ENABLED=false by default

When enabled, capture happens after thumbnail metadata validation for:
- video thumbnails
- short thumbnails

Failures are fail-open and do not modify pipeline decisions or returned payload semantics.

## Local Artifact
Integrity summary runner:
- tools/project002_sprint1e_phase5_thumbnail_metadata_lineage.py

Generated artifact path:
- artifacts/latest/project002_sprint1e_phase5_thumbnail_metadata_lineage/integrity_summary.json