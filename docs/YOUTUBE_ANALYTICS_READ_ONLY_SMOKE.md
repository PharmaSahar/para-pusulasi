# YouTube Analytics Read-Only Smoke

## Purpose

This command provides a local-only, explicitly invoked read-only smoke path for YouTube Analytics. It exists to validate the Analytics reporting API contract without mutating production configuration, scheduler state, uploads, thumbnails, or analytics stores.

## CLI

```bash
python -m src.youtube_analytics_smoke \
  --channel <channel_slug> \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --output <local_output_path>
```

An optional `--timeout-seconds` flag is available. The wrapper accepts repeated `--channel` arguments only to reject multi-channel requests; exactly one channel must be supplied.

## Safety Constraints

- The wrapper never runs from the scheduler or pipeline.
- The wrapper never enables recurring collection.
- The wrapper never changes `YOUTUBE_ANALYTICS_API_GO`.
- The wrapper never writes production analytics stores or dashboard state.
- The wrapper never refreshes, rewrites, or replaces token files.
- The wrapper never instantiates uploader code or calls mutation-capable YouTube endpoints.
- The wrapper never mutates titles, thumbnails, metadata, videos, playlists, visibility, or uploads.

## Read-Only Token Resolution

The wrapper uses only this token resolution order:

1. `cfg.youtube_analytics_token_path` (`ANALYTICS_TOKEN_PRIMARY`)
2. `cfg.token_path` (`UPLOADER_TOKEN_FALLBACK`) only when primary is missing
3. `NONE` when both are missing

No other token path is attempted.
No token refresh or OAuth login fallback is allowed.

## Allowed Query Surface

Allowed dimensions:
- `day`

Allowed metrics:
- `views`
- `estimatedMinutesWatched`
- `averageViewDuration`
- `averageViewPercentage`
- `impressions`
- `impressionClickThroughRate`
- `subscribersGained`
- `subscribersLost`

The smoke wrapper rejects any unsupported metric or dimension returned by the API.

## Result States

- `SUCCESS`
- `CONFIG_DISABLED`
- `AUTHENTICATION_BLOCKED`
- `CREDENTIAL_MISSING`
- `TOKEN_MISSING`
- `TOKEN_EXPIRED`
- `TOKEN_REFRESH_FAILED`
- `API_NOT_ENABLED`
- `API_SCOPE_INSUFFICIENT`
- `QUOTA_BLOCKED`
- `CHANNEL_MAPPING_ERROR`
- `INVALID_DATE_WINDOW`
- `UNSUPPORTED_METRIC`
- `API_REQUEST_FAILED`
- `EMPTY_RESPONSE`
- `OUTPUT_WRITE_FAILED`

## Output Schema

The output is written only to the explicit local path provided at runtime and includes:

- `schema_version`
- `generated_at`
- `mode`
- `channel_slug`
- `channel_id_hash`
- `start_date`
- `end_date`
- `requested_metrics`
- `returned_columns`
- `row_count`
- `normalized_rows`
- `result_state`
- `error_class`
- `redacted_error`
- `credential_source_present`
- `token_source_present`
- `selected_token_source` (`ANALYTICS_TOKEN_PRIMARY`, `UPLOADER_TOKEN_FALLBACK`, or `NONE`)
- `api_call_attempted`
- `api_call_succeeded`
- `mutation_attempted`
- `output_hash`

## Eligibility Note

The wrapper is ready for local invocation only when the caller explicitly enables the analytics go-decision in the shell used for that one-time command and the token material is already present. The repository does not enable this globally.