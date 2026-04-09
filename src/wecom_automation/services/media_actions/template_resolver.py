"""
Helpers for rendering media action templates from a common event context.
"""

from __future__ import annotations

from wecom_automation.services.media_actions.interfaces import MediaEvent


def build_media_template_context(event: MediaEvent) -> dict[str, str]:
    """Build the shared placeholder context used by media action templates."""
    return {
        "customer_name": event.customer_name,
        "kefu_name": event.kefu_name,
        "device_serial": event.device_serial,
    }


def render_media_template(
    template: str,
    event: MediaEvent,
    *,
    fallback: str | None = None,
    preserve_on_error: bool = False,
) -> str:
    """
    Render a template against a media event.

    When ``preserve_on_error`` is true, invalid templates fall back to the raw
    template string so operators can still see the configured content.
    """
    context = build_media_template_context(event)
    try:
        return template.format_map(_SafeDict(context) if preserve_on_error else context)
    except (KeyError, ValueError):
        if preserve_on_error:
            return template
        if fallback is not None:
            return fallback
        return template


class _SafeDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
