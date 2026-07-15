# Analytics Read-Only Smoke Minimal Release Manifest

- Production base SHA: `68529058e386661d19eaa2dfe510523d7c6cd47a`
- Wrapper source commit: `e8accd96e72af7b267e90b6ee0343293374c2e54`
- Fallback source commit: `496d1a43430a6f7416039d82eb572c13088b040d`
- Release-candidate branch: `release/analytics-readonly-smoke-68529058`
- Release-candidate HEAD SHA: `db037191b892167afe942663dbaa9ceeab2a2ca1`

## Exact branch delta

Runtime/test/doc source delta:
- `docs/YOUTUBE_ANALYTICS_READ_ONLY_SMOKE.md`
- `src/youtube_analytics_smoke.py`
- `tests/test_youtube_analytics_smoke.py`

Release-governance documentation:
- `docs/ANALYTICS_READONLY_SMOKE_MINIMAL_RELEASE_MANIFEST.md`

## Dependency compatibility result

- `src.channel_manager`: compatible
- `src.config`: compatible
- `httplib2`: compatible
- `googleapiclient.discovery`: compatible
- `googleapiclient.errors`: compatible
- `google_auth_httplib2`: compatible
- `cfg.youtube_analytics_token_path`: present
- `cfg.token_path`: present
- `cfg.client_secrets_path`: present
- Compatibility result: PASS

## Validation results

- Syntax and import validation: PASS
- Targeted wrapper tests: `24 passed`
- Existing analytics-adjacent tests on production base: `12 passed`
- Scheduler/uploader safety-adjacent tests on production base: `57 passed`
- Production readiness and cutover validation tests on production base: `41 passed`
- Full repository suite on release candidate: `685 passed`

## Wrapper safety result

- CLI-only: PASS
- Read-only: PASS
- One-channel constrained: PASS
- Seven-day-window constrained: PASS
- Zero retry: PASS
- No scheduler integration: PASS
- No pipeline integration: PASS
- No uploader import: PASS
- No dashboard write: PASS
- No analytics-store write: PASS
- No token refresh: PASS
- No token write: PASS
- No credential write: PASS
- No interactive OAuth: PASS
- No recurring execution: PASS
- No YouTube mutation endpoint: PASS

## Deployment and operational status

- Deployment status: `NOT_DEPLOYED`
- OAuth status: `UNCHANGED`
- Token status: `UNCHANGED`
- Production status: `UNCHANGED`
- Rollback base: `68529058e386661d19eaa2dfe510523d7c6cd47a`