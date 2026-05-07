"""Pure template renderer for BOSS Zhipin reply templates.

Supports two syntactic forms:

* ``{var}`` - simple placeholder. Missing placeholders are left
  literally in the output and recorded as a warning so the caller can
  surface them in tests/UI without ever raising.
* ``{?var:body}`` - conditional segment. Emitted only when ``var`` is
  present in ``context`` *and* truthy (non-empty string, non-zero
  number). The ``body`` may itself contain simple placeholders. The
  body must not contain a literal ``}``.

The renderer never raises on bad input, never invokes ``str.format``
(so curly braces in user content are safe), and truncates to
``max_length`` chars with an ellipsis to fit BOSS Zhipin message
limits.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

_DEFAULT_MAX_LENGTH: Final[int] = 480

_COND_RE: Final[re.Pattern[str]] = re.compile(
    r"\{\?(?P<var>[a-zA-Z_][a-zA-Z0-9_]*):"
    r"(?P<body>(?:[^{}]|\{[a-zA-Z_][a-zA-Z0-9_]*\})*)\}"
)
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{(?P<var>[a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class RenderResult:
    text: str
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _is_truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _substitute_simple(template: str, context: Mapping[str, Any], warnings: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        var = match.group("var")
        if var in context and context[var] is not None:
            return str(context[var])
        if var not in warnings:
            warnings.append(var)
        return match.group(0)

    return _PLACEHOLDER_RE.sub(repl, template)


def _expand_conditionals(template: str, context: Mapping[str, Any], warnings: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        var = match.group("var")
        body = match.group("body")
        if not _is_truthy(context.get(var)):
            return ""
        return _substitute_simple(body, context, warnings)

    return _COND_RE.sub(repl, template)


def render_template(
    template: str,
    context: Mapping[str, Any],
    *,
    max_length: int = _DEFAULT_MAX_LENGTH,
) -> RenderResult:
    if not template:
        return RenderResult(text="", warnings=())

    warnings: list[str] = []
    after_cond = _expand_conditionals(template, context, warnings)
    rendered = _substitute_simple(after_cond, context, warnings)

    if max_length > 0 and len(rendered) > max_length:
        rendered = rendered[: max_length - 1] + "…"

    return RenderResult(text=rendered, warnings=tuple(warnings))
