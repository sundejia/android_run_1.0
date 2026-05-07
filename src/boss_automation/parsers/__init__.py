"""UI tree parsers for BOSS Zhipin pages.

Parsers are pure functions that take a UI tree dict (as captured by the
DroidRun accessibility layer) and return typed domain objects. They MUST
be deterministic and free of I/O so they can be tested with dumped
fixtures only.
"""
