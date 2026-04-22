"""Unit tests for wecom-desktop/backend/utils/orphan_process_cleaner.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

backend_dir = Path(__file__).resolve().parent.parent.parent / "wecom-desktop" / "backend"
sys.path.insert(0, str(backend_dir))

from utils.orphan_process_cleaner import (  # noqa: E402
    _matches_realtime,
    _select_tree_roots,
    kill_realtime_reply_orphans,
)


class TestMatchesRealtime:
    def test_requires_script_name(self) -> None:
        assert not _matches_realtime("python.exe other_script.py --serial ABC", None)
        assert _matches_realtime(
            "uv run realtime_reply_process.py --serial DEVICE1",
            None,
        )

    def test_serial_none_matches_any_script(self) -> None:
        assert _matches_realtime(
            r"D:\proj\realtime_reply_process.py --tcp-port 8090 --serial XX",
            None,
        )

    def test_serial_filters(self) -> None:
        cmd = '"D:\\wecom-desktop\\backend\\scripts\\realtime_reply_process.py" --serial SERIAL_A --scan-interval 60'
        assert _matches_realtime(cmd, "SERIAL_A")
        assert not _matches_realtime(cmd, "SERIAL_B")

    def test_quoted_serial_variant(self) -> None:
        cmd = 'python realtime_reply_process.py --serial "SERIAL_X" --use-ai-reply'
        assert _matches_realtime(cmd, "SERIAL_X")


class TestSelectTreeRoots:
    def test_keeps_outermost_when_child_also_in_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import utils.orphan_process_cleaner as opc

        monkeypatch.setattr(opc, "psutil", MagicMock())

        root = MagicMock()
        root.pid = 100
        child = MagicMock()
        child.pid = 101

        root.parents.return_value = []
        child.parents.return_value = [root]

        roots = _select_tree_roots([root, child])
        assert roots == [root]

    def test_excludes_own_pid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import utils.orphan_process_cleaner as opc

        monkeypatch.setattr(opc, "psutil", MagicMock())

        own = MagicMock()
        own.pid = 99999
        monkeypatch.setattr(opc.os, "getpid", lambda: 99999)
        own.parents.return_value = []

        roots = _select_tree_roots([own])
        assert roots == []


class TestKillRealtimeReplyOrphans:
    def test_returns_zeros_when_psutil_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import utils.orphan_process_cleaner as opc

        monkeypatch.setattr(opc, "psutil", None)
        assert kill_realtime_reply_orphans("ANY") == {
            "trees_killed": 0,
            "processes_killed": 0,
        }

    def test_invokes_kill_tree_per_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import utils.orphan_process_cleaner as opc

        fake_root = MagicMock()
        fake_root.pid = 555
        kill_tree = MagicMock(return_value=7)

        monkeypatch.setattr(
            opc,
            "_iter_matching_processes",
            lambda pred: [fake_root],
        )
        monkeypatch.setattr(
            opc,
            "_select_tree_roots",
            lambda matches: [fake_root],
        )
        monkeypatch.setattr(opc, "_kill_tree", kill_tree)

        result = kill_realtime_reply_orphans("MY_SERIAL")

        assert result == {"trees_killed": 1, "processes_killed": 7}
        kill_tree.assert_called_once_with(fake_root)
