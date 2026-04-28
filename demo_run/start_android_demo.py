"""Boot a minimal android-side webhook receiver for the demo.

Reuses the e2e subprocess app (real router + real ReviewGate + recording
action). Runs on port 8000 and writes its sentinel/log into a stable
location so the tutorial can reference them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
src_dir = repo_root / "src"
backend_dir = repo_root / "wecom-desktop" / "backend"
test_dir = repo_root / "tests" / "integration"

for p in (str(src_dir), str(backend_dir), str(repo_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

DEMO_DIR = Path(__file__).resolve().parent
DB_PATH = DEMO_DIR / "android.db"
SENTINEL = DEMO_DIR / "action_invocations.log"
SECRET = "demo-secret-change-me"

os.environ["E2E_DB_PATH"] = str(DB_PATH)
os.environ["E2E_SECRET"] = SECRET
os.environ["E2E_SENTINEL"] = str(SENTINEL)
os.environ["E2E_PENDING_ID"] = "9001"
os.environ["E2E_EXTRA_PENDING_IDS"] = "9002,9003"
os.environ["REVIEW_WEBHOOK_SECRET"] = SECRET
os.environ["WECOM_DB_PATH"] = str(DB_PATH)

# Reset sentinel each demo run so screenshots show only this run's events.
if SENTINEL.exists():
    SENTINEL.unlink()

import uvicorn  # noqa: E402
from tests.integration._e2e_subprocess_app import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
