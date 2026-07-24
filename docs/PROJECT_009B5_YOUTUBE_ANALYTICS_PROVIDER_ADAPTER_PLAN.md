# PROJECT009-B5 — YouTube Analytics Provider Adapter Design Plan

## Status

PLANNED

This is a documentation-only design slice for the first real provider adapter under the PROJECT009 analytics contract. It is intentionally read-only, non-autonomous, and scoped to planning and testability. No live API calls, credential exchange, scheduler changes, or production mutation are introduced in this slice.

## 1. Objective

Design the first concrete provider adapter for the repository’s analytics provider contract, using YouTube Analytics as the initial target provider. The adapter must translate provider requests into provider-neutral rows and pages without coupling the core analytics pipeline to any live transport implementation.

## 2. Context and references

The design builds directly on the existing contract layer and the repository’s current YouTube integration helpers:

- src/analytics_provider_contract.py — canonical provider request, row, page, and error models
- src/youtube_analytics.py — current live query shape for per-video metrics
- src/youtube_auth.py — current authentication boundary and token handling
- src/youtube_analytics_smoke.py — current read-only smoke pattern and safe error classification

## 3. Design goals

1. Keep the provider boundary explicit and contract-first.
2. Preserve deterministic request identity and response identity.
3. Map YouTube Analytics responses into the existing provider-neutral contract without leaking transport details.
4. Support safe pagination and explicit error mapping.
5. Preserve channel isolation and never emit secrets or raw token payloads.
6. Produce partial-data metadata when the provider response is incomplete instead of silently inventing values.

## 4. Non-goals and safety constraints

The B5 design does not include:

- live YouTube API implementation in this slice
- OAuth flow changes or token persistence changes
- scheduler integration or runtime behavior changes
- deployment or production state mutation
- prompt, title, thumbnail, or upload automation changes
- any automatic actioning based on adapter output

## 5. Proposed adapter shape

### 5.1 Adapter class

The first implementation should introduce a provider class with the following shape:

- class YouTubeAnalyticsProvider
- constructor accepts a channel configuration object, an optional service factory, and a clock/logger dependency
- method fetch_analytics_page(request: AnalyticsProviderRequest) -> AnalyticsProviderPage

### 5.2 Internal responsibilities

The adapter should internally perform four bounded steps:

1. Build a provider-specific request from the contract request.
2. Execute the provider call through the existing auth boundary.
3. Normalize the provider response into AnalyticsProviderRow objects.
4. Return an AnalyticsProviderPage with deterministic identity and safe warnings.

## 6. Request mapping design

### 6.1 Identity mapping

The adapter must preserve the following mapping contract:

- channel_id: resolved from the repository channel registry for the requested channel
- youtube_channel_id: resolved from the same registry entry
- internal_video_id and content_job_id: resolved from local content inventory or content registry metadata when available; if unavailable, the adapter must not invent these values and should emit a partial/filtered row rather than fabricate identity
- youtube_video_id: taken from the provider response when available

### 6.2 Date and metric mapping

The adapter should map the contract request to the existing YouTube Analytics query semantics:

- start_date and end_date -> startDate/endDate
- metrics -> mapped to the provider’s supported metric names
- dimensions -> initial slice should support day-based reporting only
- content_types -> first slice should support LONG_FORM and SHORT as filters or metadata hints; the adapter should not conflate them with provider-native categories
- page_size -> mapped to maxResults with the contract upper bound preserved

### 6.3 Query family for first slice

The first implementation slice should target a narrow query family:

- daily video-level analytics rows for a single channel and date window
- one provider page per request, with optional next-page cursor support
- no multi-channel aggregation in the first slice

## 7. Row mapping design

Each provider row should be normalized into an AnalyticsProviderRow with the following semantics:

- snapshot_timestamp: the UTC timestamp at which the response was collected or the row was materialized
- publication_timestamp: sourced from local content metadata when present; otherwise the adapter must not fabricate a publication date and should mark the row partial
- title_at_snapshot, topic, topic_domain, language, duration_seconds, thumbnail_identity, prompt_template_version: populated only when the adapter has a trustworthy local source
- metrics: mapped directly to the canonical contract metric names and preserved as null when missing rather than coerced to zero
- metric_source: set to a stable value such as youtube_analytics_api
- provenance_reference: set to a stable, non-secret identifier that preserves the origin of the row
- source_query_version: set from the request query_version

## 8. Pagination and cursor semantics

The adapter should support the following pagination contract:

- request.cursor is mapped to the provider’s page token semantics
- if the provider response contains a nextPageToken, the adapter returns has_more=True and next_cursor=<token>
- if the provider response contains no next page token, the adapter returns has_more=False and next_cursor=None
- the adapter must not silently drop pagination state or emit an inconsistent page shape

## 9. Error handling and partial-data policy

### 9.1 Error taxonomy

The adapter should map provider and transport failures into the existing safe errors:

- 401 or missing permission -> AUTHENTICATION_BLOCKED or API_SCOPE_INSUFFICIENT
- 429 or quota pressure -> QUOTA_EXCEEDED or RATE_LIMITED
- 5xx or transient transport failure -> TRANSIENT_PROVIDER_ERROR
- malformed or structurally inconsistent provider response -> INVALID_PROVIDER_RESPONSE

### 9.2 Partial-data policy

The adapter should prefer explicit partial metadata over silent fabrication:

- if a required identity field is missing, skip the row and emit a warning
- if a metric is missing, preserve null and list the field in missing_fields
- if local metadata is missing for title or publication metadata, keep the row but mark completeness_status as PARTIAL and add the missing fields
- the adapter must never invent a metric value, publication date, or content identity

## 10. OAuth and credential boundary

The adapter should reuse the existing auth helpers rather than introducing a new credential path:

- use the existing channel-specific token resolution approach from src/youtube_auth.py
- rely on the existing read-only or analytics-scoped token flow already present in the repository
- never log or persist raw token values, client secrets, or full API responses
- fail closed with a safe provider error if the auth boundary is unavailable

## 11. Observability and evidence

The adapter should preserve observability consistent with the repository’s evidence-based pattern:

- include request_identity and response_identity in the page payload
- return warnings for missing metadata, pagination state, or provider-side gaps
- preserve the source query version and preferred metric mapping in the emitted row payload
- avoid storing secrets, raw OAuth artifacts, or full raw API payloads in analytics outputs

## 12. Rollout slices

### Slice 1 — contract and adapter harness

- add unit tests for request mapping, row normalization, pagination, and error taxonomy
- use an in-memory fake provider or fixture responses to validate adapter behavior
- keep all tests local and deterministic

### Slice 2 — gated live integration

- add a feature-gated adapter path behind an explicit environment flag
- keep the adapter read-only and non-autonomous
- ensure no scheduler, upload, or queue mutation is triggered by the adapter

### Slice 3 — future provider expansion

- allow the same contract to support additional providers after the YouTube adapter proves stable
- keep provider-specific logic isolated behind the adapter boundary

## 13. Acceptance matrix

| Criterion | Requirement | Evidence of completion |
| --- | --- | --- |
| Contract alignment | The adapter returns AnalyticsProviderPage objects that satisfy the existing provider contract | Unit tests asserting page shape, request identity, and row normalization |
| Deterministic identity | Repeating the same request yields the same request_identity and response_identity | Deterministic test cases with identical fixture input |
| Mapping fidelity | Request fields are translated into correct query parameters and row fields | Fixture-based tests covering date range, metric set, and content-type handling |
| Pagination | Cursor handling preserves next-page semantics without loss | Tests using mocked nextPageToken responses |
| Error handling | Provider failures map to safe, structured errors | Tests for auth, quota, and transient failure cases |
| Partial-data safety | Missing metadata is preserved as partial rather than invented | Tests proving missing_fields and completeness_status are emitted correctly |
| Channel isolation | Request channel identity is preserved and never mixed across channels | Tests asserting channel_id and youtube_channel_id propagation |
| Auth safety | The adapter uses existing auth helpers and never stores secrets | Static review and test harness verifying no new token-writing behavior |
| Observability | The adapter emits warnings and stable identifiers for each page | Unit tests and evidence artifact inspection |
| Non-impact | The design remains read-only and does not alter scheduling, upload, or production state | Design review checklist and test-only execution |

## 14. Recommended implementation order

1. Add focused unit tests around the adapter contract and error mapping.
2. Implement the provider adapter with a dependency-injected service factory.
3. Validate mapping against fixture payloads before any live run is attempted.
4. Keep live execution behind an explicit gate and only after the read-only contract is validated.

## 15. Final note

This plan is intentionally conservative. The correct next step is to implement the adapter behind the provider contract with fixture-driven tests first, then evaluate any live provider path only if the repository’s safety, evidence, and channel-isolation requirements remain intact.
