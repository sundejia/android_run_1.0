#!/usr/bin/env python3
# ruff: noqa: T201
"""
独立探测脚本（不修改、不依赖 wecom_automation 业务代码）

目的：验证企业微信 Android 语音缓存目录里，**点击播放一条语音前后**：
  - 是否出现 **新 .silk 路径**（new_files = after - before）
  - 或仅有 **mtime / size 变化**（已缓存过的语音）

用法示例（确认两条气泡各自对应哪个文件）：

  1) 第一拍「基线」（聊天页准备好，先不要点语音）：
     uv run python tests/manual/voice/inspect_voicemsg_play_delta.py --serial <序列号> snapshot -o snap0.json

  2) 在手机上只点 **第一条** 语音播放完，再执行：
     uv run python tests/manual/voice/inspect_voicemsg_play_delta.py --serial <序列号> snapshot -o snap1.json

  3) 对比：
     uv run python tests/manual/voice/inspect_voicemsg_play_delta.py diff snap0.json snap1.json

  4) 再只点 **第二条** 语音，保存 snap2.json，然后：
     uv run python tests/manual/voice/inspect_voicemsg_play_delta.py diff snap1.json snap2.json

看 diff 里的「新增路径」或「mtime/size 变化」是否每次唯一、是否与聊天顺序一致。
若两条 UI 都显示 3\" 但内容不同，应用应主要靠「本次点击引起的差异」而不是全库按时长猜。

可选：--cache-dir 覆盖默认 WeCom voicemsg 根目录。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_VOICEMSG = "/sdcard/Android/data/com.tencent.wework/files/voicemsg/"
_SILK_BASENAME_RE = re.compile(
    r"^(?P<y>\d{4})_(?P<m>\d{2})_(?P<d>\d{2})_(?P<H>\d{2})_(?P<M>\d{2})_(?P<S>\d{2})_(?P<ms>\d+)\.silk$"
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _resolve_adb() -> str:
    bundled = _project_root() / "wecom-desktop" / "scrcpy" / "adb.exe"
    if bundled.exists():
        return str(bundled)
    return "adb"


def _adb_shell(adb: str, serial: str | None, script: str, *, timeout: int = 120) -> str:
    cmd = [adb]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["shell", script])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.stderr.write(f"adb shell failed (code={r.returncode})\n{r.stderr}\n")
    return r.stdout


def snapshot_silk_stats(adb: str, serial: str | None, voice_cache_path: str) -> dict[str, list[int]]:
    """
    Remote: path -> [mtime_epoch, size].
    """
    inner = (
        f"find {voice_cache_path} -name '*.silk' -type f 2>/dev/null | "
        "while IFS= read -r f; do "
        "st=$(stat -c '%Y %s' \"$f\" 2>/dev/null) || continue; "
        "echo \"$st|$f\"; "
        "done"
    )
    raw = _adb_shell(adb, serial, inner, timeout=120)
    out: dict[str, list[int]] = {}
    for line in raw.splitlines():
        line = line.strip().replace("\r", "")
        if not line or "|" not in line:
            continue
        left, path = line.rsplit("|", 1)
        path = path.strip()
        parts = left.split()
        if len(parts) < 2:
            continue
        try:
            mtime, size = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if path.endswith(".silk"):
            out[path] = [mtime, size]
    return out


def _basename_embedded_label(path: str) -> str:
    name = path.split("/")[-1]
    if _SILK_BASENAME_RE.match(name):
        return name.replace(".silk", "")
    return name


def save_snapshot(
    adb: str,
    serial: str | None,
    voice_cache_path: str,
    out_path: Path,
) -> None:
    data = snapshot_silk_stats(adb, serial, voice_cache_path)
    payload = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "serial": serial,
        "voice_cache_path": voice_cache_path,
        "count": len(data),
        "paths": data,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(data)} silk entries -> {out_path}")


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_snapshots(a_path: Path, b_path: Path) -> None:
    a = load_snapshot(a_path)
    b = load_snapshot(b_path)
    pa = {k: tuple(v) for k, v in a["paths"].items()}
    pb = {k: tuple(v) for k, v in b["paths"].items()}
    sa, sb = set(pa), set(pb)

    new_paths = sorted(sb - sa)
    removed = sorted(sa - sb)
    common = sa & sb

    changed: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
    for p in sorted(common):
        if pa[p] != pb[p]:
            changed.append((p, pa[p], pb[p]))

    print("=== voicemsg .silk diff ===")
    print(f"A: {a_path.name}  ({a.get('captured_at_utc')})  n={len(pa)}")
    print(f"B: {b_path.name}  ({b.get('captured_at_utc')})  n={len(pb)}")
    print()

    if new_paths:
        print(f"-- NEW in B ({len(new_paths)}) --")
        for p in new_paths:
            m, s = pb[p]
            print(f"  mtime={m} size={s}  embedded={_basename_embedded_label(p)}")
            print(f"    {p}")
        print()

    if removed:
        print(f"-- REMOVED from A ({len(removed)}) --")
        for p in removed:
            print(f"    {p}")
        print()

    if changed:
        print(f"-- MTIME or SIZE changed ({len(changed)}) --")
        for p, (m0, s0), (m1, s1) in changed:
            print(f"  embedded={_basename_embedded_label(p)}")
            print(f"    mtime {m0} -> {m1}  |  size {s0} -> {s1}")
            print(f"    {p}")
        print()

    if not new_paths and not removed and not changed:
        print("(no path set / stat changes between A and B)")
        print("  说明：若你刚播过语音仍无变化，可能是 find/stat 与真机 shell 不兼容，或缓存未刷新。")

    # Heuristic summary for「这一条语音更像对应哪个文件」
    if len(new_paths) == 1:
        print(">>> 推断：本次操作 **唯一新增** 文件，极可能即刚播放的那条语音缓存。")
    elif len(new_paths) > 1:
        print(">>> 推断：多条新增，需结合 mtime 最新或播放顺序进一步区分。")
    elif len(changed) == 1:
        p, (m0, s0), (m1, s1) = changed[0]
        print(
            f">>> 推断：**无新路径**，仅 1 个文件 mtime/size 变化，可能即刚播放的已缓存语音。\n    {p}"
        )
    elif len(changed) > 1:
        best = max(changed, key=lambda x: x[2][0])
        print(
            ">>> 推断：多条 stat 变化，默认 **mtime 最大** 更可能是刚写入/触达的：\n"
            f"    {best[0]}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="Inspect WeCom voicemsg SILK before/after play (standalone)")
    p.add_argument("--serial", default=None, help="ADB serial (optional if only one device)")
    p.add_argument("--cache-dir", default=_DEFAULT_VOICEMSG, help="WeCom voicemsg root on device")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("snapshot", help="Dump all .silk mtime+size to JSON")
    ps.add_argument("-o", "--output", type=Path, required=True, help="Output JSON path")

    pd = sub.add_parser("diff", help="Compare two snapshot JSON files")
    pd.add_argument("before", type=Path)
    pd.add_argument("after", type=Path)

    args = p.parse_args()
    adb = _resolve_adb()

    if args.cmd == "snapshot":
        save_snapshot(adb, args.serial, args.cache_dir, args.output)
    elif args.cmd == "diff":
        diff_snapshots(args.before, args.after)
    else:
        p.error("unknown command")


if __name__ == "__main__":
    main()
