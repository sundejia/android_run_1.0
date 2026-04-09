# Media auto-actions: custom post-group message and chat header menu compatibility

> **Status**: Implemented  
> **Last updated**: 2026-04-05

## Summary

This iteration adds three related capabilities:

1. **Configurable message after auto group creation** — Operators set a global default template under `media_auto_actions.auto_group_invite` (`send_test_message_after_create`, `test_message_text`). Placeholders `{customer_name}`, `{kefu_name}`, `{device_serial}` are rendered in `AutoGroupInviteAction` before `GroupInviteWorkflowService` sends the final string (workflow layer does not parse templates).
2. **API and desktop UI alignment** — FastAPI `AutoGroupInviteSettings` and `DEFAULT_SETTINGS` include the same fields as `settings_loader` / DB seeds so `PUT /api/media-actions/settings` does not drop keys. The Media Auto-Actions page exposes the message switch, template textarea, variable hints, and a live preview (sample agent name for preview only).
3. **Enterprise WeCom header menu detection** — Some builds expose the chat “more” action as clickable `TextView` / `RelativeLayout` nodes with opaque text (e.g. `nma`, `nml`) and no useful `contentDescription`. `WeComService._find_group_invite_menu_button` now recursively collects top-right header candidates and treats those layouts as valid menu targets when they are clickable and within the header band.

## Key files

| Area                        | Path                                                                       | Role                                                                          |
| --------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Template rendering (Python) | `src/wecom_automation/services/media_actions/template_resolver.py`         | Shared `str.format`-style context for group name and message templates        |
| Auto group invite           | `src/wecom_automation/services/media_actions/actions/auto_group_invite.py` | Resolves group name and post-group message from `MediaEvent` + settings       |
| Chat header menu            | `src/wecom_automation/services/wecom_service.py`                           | `_collect_header_action_candidates`, `_is_image_like_click_target` extensions |
| Settings API                | `wecom-desktop/backend/routers/media_actions.py`                           | Pydantic models and defaults for full `auto_group_invite` JSON                |
| Desktop UI                  | `wecom-desktop/src/views/MediaActionsView.vue`                             | Form + preview                                                                |
| Preview helper (TS)         | `wecom-desktop/src/utils/mediaActionTemplates.ts`                          | Client-side preview aligned with allowed placeholders                         |
| i18n                        | `wecom-desktop/backend/i18n/translations.py`                               | New `media_actions.*` strings (en / zh-CN)                                    |

## `POST /api/media-actions/test-trigger` semantics (corrected)

The handler **constructs a synthetic `MediaEvent`** and a **local `MediaEventBus`**; it does **not** use `build_media_event_bus` or inject `WeComService`.

- **`AutoBlacklistAction`** uses `BlacklistWriter()` with default DB paths and can perform real blacklist side effects when enabled.
- **`AutoGroupInviteAction`** is wired with `GroupChatService()` **without** a `wecom_service`. In that mode, group creation is **not** executed on the device; the service records intent / returns success paths that do not reflect real UI automation. Backend logs may include `No WeComService available; recording group creation intent only`.

**Do not** use this endpoint to validate that a message appeared in the WeCom UI. For real-device validation, run the sync/realtime path with a connected device or invoke `GroupChatService(wecom_service=...)` / `AutoGroupInviteAction` from a context that supplies `WeComService` (as in production factories).

## Tests added or extended

| Test file                                               | Coverage                                                                     |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `tests/unit/test_auto_group_invite_action.py`           | Message template rendering and unknown placeholder behavior                  |
| `tests/unit/test_group_invite_workflow.py`              | Workflow receives already-rendered text                                      |
| `wecom-desktop/backend/tests/test_media_actions_api.py` | GET/PUT preserve `test_message_text`, `send_test_message_after_create`, etc. |
| `tests/unit/test_wecom_service_opt.py`                  | Header menu fallback recursion and clickable `RelativeLayout`                |
| `wecom-desktop/src/views/mediaActions.spec.ts`          | API client shapes for new fields                                             |
| `wecom-desktop/src/views/MediaActionsView.spec.ts`      | UI controls and save payload                                                 |

## Live device check (2026-04-05)

On a connected device, after the header-menu fix, an end-to-end run with a unique template string was confirmed: the accessibility/UI tree contained the same rendered text as the configured template (customer name + device serial substituted). **DroidRun Portal** must stay healthy; avoid `uiautomator dump` on the same device session (see fixed bug doc below).

## Related documentation

- [Media Auto-Actions feature](../features/media-auto-actions.md)
- [Android group invite workflow](2026-04-04-android-group-invite-workflow.md)
- [DroidRun Portal / UiAutomator conflict](../04-bugs-and-fixes/fixed/BUG-2025-12-13-droidrun-portal-connection-failure.md)
