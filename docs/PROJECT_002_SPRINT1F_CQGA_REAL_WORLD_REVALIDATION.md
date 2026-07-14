# PROJECT 002 - Sprint 1F

## CQGA Real-World Revalidation with Enriched Evidence

### Scope

Sprint 1F performs the first full local revalidation pass of CQGA using the enriched evidence chain produced in previous sprints.

This sprint is measurement-only.

It does not:

- recalibrate CQGA
- change CQGA scoring or weights
- change recommendations logic
- change pipeline outputs
- modify scheduler or uploader behavior
- mutate historical evidence

### Safety Contract

- local-only
- deterministic replay
- append-only artifacts
- advisory-only outputs
- default-off runtime impact (no runtime hooks introduced)
- fail-open by construction (analysis-only path)
- pipeline_output_changed=false

### Implemented Components

- Source module: src/cqga_real_world_revalidation.py
- Runner: tools/project002_sprint1f_cqga_real_world_revalidation.py
- Test suite: tests/test_cqga_real_world_revalidation.py

### Methodology

1. Evidence audit
- Audits deterministic availability for planning lineage, blueprint lineage, prompt metadata, script lineage, thumbnail metadata, render metadata, upload metadata, analytics linkage, ownership, and forward evidence.
- Produces evidence_completeness_matrix.json.
- Missing evidence is reported only; no repair flow is executed.

2. CQGA input reconstruction
- Reconstructs input objects by joining runtime evidence, ownership snapshots, canonical analytics, and CQGA storage rows.
- Required fields are verified directly and explicitly tracked:
  - title
  - thumbnail prompt
  - thumbnail metadata
  - script
  - description
  - hashtags
  - tags
  - playlist
  - cards
  - end screen
  - analytics
  - ownership
  - channel profile
- No inference or guessing is performed for absent fields.

3. Deterministic replay
- Replays CQGA over reconstructable records only.
- Repeats replay multiple times and verifies identical normalized outputs.
- Confirms stability for rankings, explanations, root causes, and recommendations.

4. Agreement analysis
- Compares predicted weaknesses with observed analytics-derived weaknesses where observed metrics exist.
- Supports at minimum: CTR, retention, average percentage viewed, watch time, shorts completion, discovery, playlist usage, and traffic source (if available).
- If observed metrics are absent, metrics are reported as not applicable.

5. Root-cause validation
- Computes root-cause overlap between predicted and observed weakness signatures.
- Produces root-cause agreement and severity agreement.

6. Metric outputs
- precision
- recall
- specificity
- F1
- balanced accuracy
- ROC-AUC (when class distribution allows)
- Matthews correlation coefficient
- Cohen's Kappa
- ranking agreement
- root-cause agreement
- severity agreement
- false positives
- false negatives
- confidence calibration

7. Coverage and exclusions
- Reports total reconstructed, replayable, excluded, complete evidence, partial evidence, missing evidence, and coverage percent.
- Exclusions are explicit and deterministic.

8. Advisory review payloads
- Emits review payloads with predicted issues and recommended actions.
- No automatic actions are generated.
- automatic_action remains null.

9. Gap report
- Reports unresolved evidence constraints preventing stronger validation.
- Includes known local-only limitations, including Studio-only diagnostics and unavailable granular funnel/segment data.

### Output Artifacts

Generated under artifacts/latest/project002_sprint1f_cqga_real_world_revalidation:

- evidence_completeness_matrix.json
- reconstructed_inputs.jsonl
- replay_results.jsonl
- agreement_metrics.json
- stability_report.json
- coverage_report.json
- review_payloads.jsonl
- gap_report.json
- assessment_summary.json

### Readiness Assessment Rules

Sprint 1F is considered ready for commit when all are true:

- deterministic replay proven
- stable rankings/explanations/root causes/recommendations proven
- advisory_only=true throughout artifacts
- pipeline_output_changed=false throughout artifacts
- targeted tests pass
- full regression suite passes
- append-only artifact generation preserved

### Limitations

- Agreement and calibration quality depend on observed analytics availability.
- If canonical analytics rows are linked but metrics are unavailable/unknown, statistical power is constrained.
- This sprint intentionally does not remediate missing evidence.
