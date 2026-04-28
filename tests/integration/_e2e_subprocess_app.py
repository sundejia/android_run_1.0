"""Minimal android-side ASGI app used by the cross-process E2E test.

Boots in its own ``uvicorn`` subprocess, imports the *real* webhook
router and review-gate runtime, but overrides
``_register_default_actions`` to install a recording action that writes
its invocations to a sentinel file. The test process then polls that
file to confirm the full chain executed end-to-end across the network.

Environment contract (set by the parent test):
    E2E_DB_PATH      : absolute path to the SQLite DB
    E2E_SECRET       : HMAC secret shared with the test
    E2E_SENTINEL     : path to a file the action will append a line to
    E2E_PENDING_ID   : message_id to pre-seed pending_reviews with
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[2] / "wecom-desktop" / "backend"
src_dir = Path(__file__).resolve().parents[2] / "src"
for p in (str(backend_dir), str(src_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import FastAPI  # noqa: E402

import services.review_gate_runtime as runtime_module  # noqa: E402
from routers.webhooks import router as webhooks_router  # noqa: E402
from wecom_automation.database.schema import init_database  # noqa: E402
from wecom_automation.services.media_actions.event_bus import MediaEventBus  # noqa: E402
from wecom_automation.services.media_actions.interfaces import (  # noqa: E402
    ActionResult,
    ActionStatus,
    IMediaAction,
)
from wecom_automation.services.review.gate import ReviewGate  # noqa: E402
from wecom_automation.services.review.policy import PolicyEvaluator  # noqa: E402
from wecom_automation.services.review.storage import (  # noqa: E402
    PendingReviewRow,
    ReviewStorage,
)

DB_PATH = os.environ["E2E_DB_PATH"]
SENTINEL_PATH = Path(os.environ["E2E_SENTINEL"])
SECRET = os.environ["E2E_SECRET"]
PENDING_ID = int(os.environ["E2E_PENDING_ID"])

os.environ["REVIEW_WEBHOOK_SECRET"] = SECRET


class _RecordingAction(IMediaAction):
    @property
    def action_name(self) -> str:
        return "e2e-recorder"

    async def should_execute(self, event, settings: dict) -> bool:
        return True

    async def execute(self, event, settings: dict) -> ActionResult:
        SENTINEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SENTINEL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                "|".join(
                    [
                        str(event.event_type),
                        str(event.message_id),
                        str(event.customer_id),
                        str(event.device_serial),
                    ]
                )
                + "\n"
            )
        return ActionResult(
            action_name=self.action_name,
            status=ActionStatus.SUCCESS,
            message="recorded",
        )


def _bootstrap() -> None:
    """Pre-seed the DB and override the runtime to use our recording bus.

    For the demo we seed three pending rows so the dispatcher can produce
    multiple verdicts (approved + rejected) without the gate short-circuiting
    with "no pending review".
    """
    init_database(DB_PATH, force_recreate=True)
    storage = ReviewStorage(DB_PATH)

    seed_ids = [PENDING_ID]
    extra = os.environ.get("E2E_EXTRA_PENDING_IDS", "")
    if extra:
        seed_ids.extend(int(x) for x in extra.split(",") if x.strip())

    for mid in seed_ids:
        try:
            storage.insert_pending_review(
                PendingReviewRow(
                    message_id=mid,
                    customer_id=1,
                    customer_name=f"customer-{mid}",
                    device_serial="demo-dev",
                    channel=None,
                    kefu_name="kefu",
                    image_path=f"/tmp/demo-{mid}.png",
                )
            )
        except Exception:
            # Already inserted from a previous run within the same test
            pass

    bus = MediaEventBus()
    bus.register(_RecordingAction())

    gate = ReviewGate(
        storage=storage,
        bus=bus,
        settings_provider=lambda: {},
        evaluator=PolicyEvaluator(),
    )

    runtime_module._singleton["gate"] = gate
    runtime_module._singleton["bus"] = bus
    runtime_module._singleton["storage"] = storage


_bootstrap()

app = FastAPI()
app.include_router(webhooks_router, prefix="/api/webhooks")
