# OAuth Recovery Incident Closure (2026-07)

## Incident Summary
A production OAuth incident caused YouTube credential refresh failures (`invalid_grant`) on the nine active channels. A controlled incident workflow was executed to restore valid OAuth authorization per channel, verify channel identity, and confirm production remained stable.

## Timeline (UTC)
- 2026-07-14: Incident closeout verification completed.
- 2026-07-14: Sequential channel-by-channel OAuth reauthorization completed for all affected active channels.
- 2026-07-14: Post-reauthorization identity, refresh, and Data API read verification completed.
- 2026-07-14: Production gates re-verified (release/SHA/symlink unchanged; service healthy).

## Symptoms
- Telegram and operational checks indicated OAuth refresh failures.
- Multiple active channels reported `invalid_grant` refresh errors.
- Processing risk: channel prechecks and upload-path auth were blocked until recovery.

## Root Cause
Refresh authorizations for the affected active channels were expired or revoked, causing token refresh to fail.

## Affected Channels
- `para_pusulasi`
- `borsa_akademi`
- `kripto_rehber`
- `kariyer_pusulasi`
- `girisim_okulu`
- `saglik_pusulasi`
- `teknoloji_pusulasi`
- `egitim_rehberi`
- `gayrimenkul_tv`

## Recovery Procedure (Operational)
- Confirmed canonical channel mapping from registry.
- Preserved pre-incident credential backups.
- Reauthorized channels sequentially using channel-specific flow (`setup_channel.py <channel_id>`).
- Verified each channel with read-only checks:
  - forced refresh
  - `channels.list(part="id,snippet", mine=True)`
  - authenticated channel ID match against expected registry ID
- Enforced restrictive token file mode after renewal.

## Channel Recovery Matrix
| canonical channel ID | recovery completed | refresh verified | channel identity verified | Data API verified | Analytics API status |
|---|---|---|---|---|---|
| para_pusulasi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| borsa_akademi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| kripto_rehber | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| kariyer_pusulasi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| girisim_okulu | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| saglik_pusulasi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| teknoloji_pusulasi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| egitim_rehberi | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |
| gayrimenkul_tv | yes | yes | yes | yes | ANALYTICS_TOKEN_MISSING |

## Production Gate Record
- release unchanged: yes
- SHA unchanged: yes
- symlink unchanged: yes
- exactly one scheduler running: yes
- health-check passed: yes
- no `invalid_grant` after recovery window checks: yes
- no forced uploads executed during recovery: yes
- no deployment executed: yes

## Security Precautions
- No token values, refresh tokens, OAuth codes, or client secret contents were exposed in incident documentation.
- Credential backups were retained.
- No credential material was committed.
- No credential artifacts were moved into source control paths.

## Remaining Operational Follow-up
- Analytics OAuth/readiness remains a separate operational task.
- If analytics reporting is needed, run dedicated analytics-consent/token workflow per channel.
