# PROJECT009-B5.4 — YouTube Analytics Live Transport Design

## Status

PLANNED

This document defines the future live transport design for YouTube Analytics while preserving the existing provider contract. It is documentation-only and does not introduce runtime code, OAuth flows, network activity, scheduler behavior, deployment changes, or production mutation.

## 1. Objective

Define a future live transport path for YouTube Analytics that:

- preserves the existing provider-neutral contract from the repository,
- keeps the transport boundary explicit and isolated,
- supports read-only analytics retrieval only,
- translates provider failures into safe, contract-compatible errors,
- and remains safe for future rollout behind explicit gates.

## 2. Design constraints

### In scope

- architecture and transport boundary design,
- credential injection design,
- retry and quota strategy,
- error translation design,
- observability and rollout planning.

### Out of scope

- live implementation,
- OAuth implementation,
- network calls during this slice,
- scheduler changes,
- deployment changes,
- production mutations,
- direct dependency on Google client libraries in this repository slice.

## 3. Architectural position

The live transport is a future adapter layer that sits between the provider contract and the external YouTube Analytics service. It must not leak transport details into the analytics pipeline.

The core rule is:

- the analytics pipeline consumes AnalyticsProviderRequest, AnalyticsProviderPage, AnalyticsProviderRow, and AnalyticsProviderError,
- the transport layer is responsible only for provider-specific request building, credential resolution, provider invocation, response normalization, and safe error translation.

## 4. Component diagram

```text
+----------------------------+
| Analytics Consumer         |
| (existing pipeline)        |
+-------------+--------------+
              |
              v
+-----------------------------------------------+
| Provider Contract Boundary                    |
| - AnalyticsProviderRequest                   |
| - AnalyticsProviderPage                      |
| - AnalyticsProviderRow                       |
| - AnalyticsProviderError                     |
+--------------------+--------------------------+
                     |
                     v
+---------------------------------------------------+
| Future YouTube Analytics Transport Adapter       |
| - request mapping                                 |
| - credential resolution                           |
| - transport execution                            |
| - response normalization                         |
| - error translation                              |
+--------------------+------------------------------+
                     |
                     v
+---------------------------------------------------+
| Credential Boundary                               |
| - credential provider contract                   |
| - channel-scoped descriptor resolution           |
| - no raw secret propagation                      |
+--------------------+------------------------------+
                     |
                     v
+---------------------------------------------------+
| External YouTube Analytics Service               |
| - read-only analytics endpoint                   |
| - quota governed                                 |
| - auth governed                                   |
+---------------------------------------------------+
```

## 5. Request lifecycle

The future live transport should follow a strict sequence:

1. Receive an AnalyticsProviderRequest from the contract boundary.
2. Validate the request shape against the existing contract semantics.
3. Resolve a channel-scoped credential descriptor through the existing credential provider boundary.
4. Build a provider-specific query payload from the contract request.
5. Execute the transport call through a dependency-injected transport abstraction.
6. Normalize the provider response into AnalyticsProviderRow values.
7. Preserve partial-data semantics instead of fabricating missing values.
8. Return an AnalyticsProviderPage containing deterministic identity, paging state, and safe warnings.

The transport must never mutate production state, queue state, or scheduler state.

## 6. Credential injection design

### Boundary

Credential resolution stays outside the analytics contract and outside the provider row model.

The live transport should receive credential resolution through a dependency-injected boundary such as:

- CredentialProviderRequest
- CredentialDescriptor
- CredentialProvider

### Injection model

The transport design should use the following flow:

- the analytics request is received,
- the transport asks the credential provider for a channel-scoped descriptor,
- the descriptor is passed to the transport implementation,
- the transport uses only the descriptor metadata and a provider-specific execution wrapper,
- the analytics pipeline never sees raw credentials or secrets.

### Safety requirements

- raw tokens must never be logged,
- raw tokens must never be persisted in analytics artifacts,
- credential failures must be translated into safe provider errors,
- the transport must fail closed if credential resolution is unavailable.

## 7. OAuth boundary

The live transport design must keep OAuth strictly outside the analytics provider contract.

### Proposed boundary

- OAuth is treated as an external credential acquisition concern.
- The transport adapter should not implement OAuth directly.
- The credential boundary should resolve a credential descriptor that is already authorized or already available from a trusted external mechanism.
- If the credential boundary cannot provide a usable descriptor, the transport returns a safe provider error rather than attempting a new login flow.

### Explicit non-goals in this slice

- no OAuth grant flow,
- no refresh token persistence,
- no client secret handling in the repository layer,
- no browser-based auth workflow.

## 8. Transport abstraction

The future transport should be expressed through an explicit abstraction so that the analytics contract remains independent from the live provider implementation.

### Recommended abstraction contract

The abstraction should define a narrow, read-only boundary with:

- request construction from AnalyticsProviderRequest,
- execution of a provider-specific query,
- normalization into AnalyticsProviderPage,
- translation of provider failures into safe error categories,
- propagation of request identity and warnings.

### Design principle

The analytics pipeline should depend on the contract layer and the transport abstraction, not on concrete Google API objects or ad hoc network wrappers.

## 9. Retry policy

The live transport should use conservative retry behavior.

### Retry rules

- Retry only for transient and rate-related failures.
- Do not retry validation failures, permission failures, or malformed-response failures.
- Use a small bounded retry count to avoid amplifying quota pressure.

### Recommended policy

- max attempts: 3 total attempts,
- initial backoff: 1 second,
- multiplier: 2x,
- jitter: full jitter,
- max backoff: 15 seconds,
- stop retrying when the provider returns a non-retryable error.

### Exponential backoff

The design should use exponential backoff with jitter:

- attempt 1: immediate attempt,
- attempt 2: backoff of roughly 1s + jitter,
- attempt 3: backoff of roughly 2s + jitter.

If the provider returns a Retry-After header or a safe retry-after value, the transport should honor it before retrying.

## 10. Quota exhaustion handling

Quota pressure is expected to be a first-class failure mode for a live provider.

### Design strategy

- classify 429, quota-exhausted, and similar responses as quota-related errors,
- surface them as safe, contract-compatible errors such as RATE_LIMITED or QUOTA_EXCEEDED,
- preserve the request identity and a retry-after value when present,
- avoid repeated immediate retries when quota is clearly exhausted,
- use a short circuit or cooldown window for the affected channel and request family.

### Operational behavior

The transport should not silently continue under quota pressure. Instead, it should:

- fail closed with a safe provider error,
- expose a retryable signal for downstream orchestration,
- and leave the queue and scheduler untouched in this design slice.

## 11. Timeout policy

The live transport should use explicit request timeouts to avoid hanging reads.

### Recommended values

- connection timeout: 5 seconds,
- read timeout: 15 seconds,
- total request timeout: 20 seconds.

These values should be configurable later through a safe runtime setting, but the default policy should remain conservative and bounded.

## 12. Error translation

The live transport should translate provider-specific failures into the existing safe error model.

### Recommended translation map

- authentication or permission failure -> safe provider error with a non-sensitive message,
- quota pressure -> RATE_LIMITED or QUOTA_EXCEEDED,
- transient transport failure -> TRANSIENT_PROVIDER_ERROR,
- malformed or structurally inconsistent payload -> INVALID_PROVIDER_RESPONSE,
- invalid date range or unsupported request shape -> contract-safe validation error.

### Translation rules

- do not expose raw provider payloads in analytics outputs,
- preserve a stable request identity,
- include retryability information where appropriate,
- keep the error category aligned with the provider contract contract semantics.

## 13. Observability plan

Observability should be designed around evidence and traceability rather than raw transport dumps.

### Logging

The transport should emit structured logs containing:

- request_identity,
- channel_id,
- youtube_channel_id,
- query family,
- attempt number,
- outcome category,
- latency,
- retry decision,
- quota or timeout signal.

### Metrics

Recommended metrics:

- analytics_transport_requests_total,
- analytics_transport_success_total,
- analytics_transport_errors_total,
- analytics_transport_retry_total,
- analytics_transport_latency_ms,
- analytics_transport_quota_errors_total,
- analytics_transport_timeout_total,
- analytics_transport_partial_rows_total.

### Tracing and evidence

- preserve request_identity across retries and error surfaces,
- record warnings for partial rows or missing metadata,
- avoid logging secrets, raw access tokens, or full provider payloads,
- keep the emitted page payload deterministic and contract-safe.

## 14. Test strategy

The design should be validated through deterministic, local tests only.

### Test layers

1. Contract compatibility tests
   - verify that the transport output still satisfies the existing provider contract.

2. Mapping tests
   - verify request-to-query mapping and row normalization semantics.

3. Retry and error taxonomy tests
   - verify backoff behavior, retry policy boundaries, and error translation.

4. Partial-data tests
   - verify that missing metrics and missing metadata remain explicit rather than fabricated.

5. No-network safety tests
   - ensure the transport design remains non-executing in this slice and can be exercised with fixtures only.

## 15. Rollout plan

### Phase 0 — design only

- document the transport boundary,
- define the contract-preserving adapter shape,
- define retry and quota behavior,
- define observability requirements.

### Phase 1 — harness and fixture-driven validation

- add unit tests for request mapping and error translation,
- validate transport normalization against controlled fixture payloads,
- keep all execution local and deterministic.

### Phase 2 — gated live readiness

- introduce feature flags or explicit runtime gates,
- keep the transport read-only,
- require observability and safe error handling before any live execution.

### Phase 3 — optional production use

- only after the contract, observability, and error handling have proven stable,
- and only under explicit operational control.

## 16. Summary

The recommended future design keeps the live transport fully isolated behind the provider contract. It preserves deterministic identities, avoids secret exposure, uses explicit partial-data semantics, handles quota and retry safely, and remains compatible with the repository’s evidence-first operating model.
