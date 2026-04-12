# Group invite diagnostics (local output)

This directory holds **machine-generated** reports from `scripts/diagnose_group_invite.py` (JSON + text summaries) and ad-hoc E2E log captures.

- **Not tracked in git** (see root `.gitignore`) to avoid large JSON blobs and device-specific UI dumps.
- **Regenerate** after connecting devices:

```bash
set PYTHONPATH=src
python scripts/diagnose_group_invite.py
```

Outputs are named like `group_invite_raw_YYYYMMDD_HHMMSS.json` and `group_invite_diagnosis_*.txt` in this folder.
