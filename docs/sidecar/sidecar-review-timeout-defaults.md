# Sidecar review timeout defaults

**Status:** Current behaviour as of 2026-04-15  
**Scope:** Human review wait on the Sidecar queue (`POST /sidecar/{serial}/queue/wait/{message_id}` and callers)

---

## Summary

The **daytime** default for how long automation blocks waiting for an operator to send or cancel a Sidecar-queued message was reduced from **300 seconds (5 minutes)** to **60 seconds**. **Night mode** still uses **`night_mode_sidecar_timeout`** (default **30 seconds**) during configured night hours.

Operators can change both values in desktop settings (SIDECAR category). Existing databases keep whatever value was already stored; only **new seeds** and **code fallbacks** use the new defaults.

---

## Where defaults apply

| Location                                                       | Role                                                                     |
| -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `wecom-desktop/backend/services/settings/defaults.py`          | Seeded DB default for `sidecar_timeout`                                  |
| `wecom-desktop/backend/services/settings/models.py`            | `SidecarSettings.sidecar_timeout` dataclass default                      |
| `wecom-desktop/backend/services/followup/response_detector.py` | `_get_sidecar_timeout()` fallbacks when settings cannot be read          |
| `wecom-desktop/backend/routers/sidecar.py`                     | FastAPI `wait_for_send(..., timeout=...)` query default                  |
| `src/wecom_automation/services/integration/sidecar.py`         | `SidecarQueueClient.wait_for_send(..., timeout=...)` default             |
| `src/wecom_automation/services/sync/customer_syncer.py`        | Initial sync path still passes an explicit timeout (aligned to **60** s) |
| `wecom-desktop/src/services/api.ts`                            | `waitForSidecarSend` default query parameter                             |

Follow-up / realtime paths use **`_get_sidecar_timeout()`**, which reads `sidecar_timeout` / `night_mode_sidecar_timeout` from settings (with **60** / **30** second fallbacks).

---

## Rationale

A five-minute wait increased latency when no one was at the Sidecar UI. Sixty seconds sits in the requested **30–60** second band while leaving a short buffer for review; night mode remains stricter at 30 seconds.

---

## Related documentation

- [System robustness fixes (2026-04-09)](../implementation/2026-04-09-system-robustness-fixes.md) — original introduction of `sidecar_timeout` and night-mode fields (values updated 2026-04-15; see that doc’s update section).
- Older bug write-ups under `docs/04-bugs-and-fixes/active/` may still describe incidents that used the previous 300 s default; timelines there are historical.
