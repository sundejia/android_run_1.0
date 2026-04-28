"""Versioned, modular policy skills.

Skills encapsulate decision logic that can be swapped without rewriting the
runtime. Each skill family lives in its own subpackage (``approval_policy``,
``governance``, ...) and exposes a ``vN`` module per version.

This layout supports the "Updatable" and "Compounding" requirements: every
verdict persists the active ``skill_version`` so historical decisions remain
explainable and replayable when policies evolve.
"""
