# Strict Evidence LaunchAgent (macOS)

Daily automation for strict read-only evidence report generation.

## What It Runs
- Script: `ops/generate_strict_evidence_report.py`
- Mode: `--latest-only`
- Output: `logs/strict_evidence_report_latest.md`

## Manager Script
- `ops/strict_evidence_launchagent.sh`

Commands:

```bash
# Install daily run at 03:15 local time
ops/strict_evidence_launchagent.sh install

# Install with custom time
ops/strict_evidence_launchagent.sh install --hour 4 --minute 5

# Check load/status
ops/strict_evidence_launchagent.sh status

# Trigger immediate run
ops/strict_evidence_launchagent.sh run-now

# Remove job
ops/strict_evidence_launchagent.sh uninstall
```

## LaunchAgent Details
- Label: `com.parapusulasi.strict-evidence-report`
- Plist path: `~/Library/LaunchAgents/com.parapusulasi.strict-evidence-report.plist`
- Stdout: `logs/launchagent_strict_evidence_out.log`
- Stderr: `logs/launchagent_strict_evidence_err.log`

## Safety Notes
- Read-only report generation only.
- No production scheduler mutation.
- No git commit/merge automation.
