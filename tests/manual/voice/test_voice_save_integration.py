#!/usr/bin/env python3
"""
独立语音集成测试：当前聊天页可见语音 → 下载 WAV → VoiceMessageHandler 入库 / voices 表 / extra_info 去重

前置条件：
  - 手机已打开企业微信并与某联系人的聊天界面（至少一条语音在屏幕上；建议两条均在可见区域）
  - USB 调试已开，adb devices 可见
  - 建议安装 pilk（SILK 转 WAV）：uv pip install pilk

用法（跑两轮：第一轮应新增，第二轮应全部去重跳过）：
  uv run python tests/manual/voice/test_voice_save_integration.py --serial <ADB序列号> --customer <客户名>

可选：
  --channel   客户渠道（与库里一致时便于复用客户）
  --db        专用 SQLite 路径（默认 tests/manual/voice/voice_manual_test.db）
  --fresh-db  运行前删除上述 DB 文件（首轮「至少新增 1 条」需空库；否则会因去重全跳过而失败）
  --debug     更详细日志

说明：
  - 仅从当前一屏 UI 解析消息，不滚动整段会话；每条语音会点击播放并从 voicemsg 缓存拉取。
  - 默认使用独立 DB，不写主库 wecom_conversations.db（除非你把 --db 指过去）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path：必须在任何项目 import 之前
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "wecom-desktop" / "backend"))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Voice save + dedupe integration test (current chat screen)")
    p.add_argument("--serial", required=True, help="ADB device serial")
    p.add_argument("--customer", required=True, help="Customer name (for customers.name in test DB)")
    p.add_argument("--channel", default=None, help="Customer channel (optional)")
    p.add_argument(
        "--db",
        default=str(_SCRIPT_DIR / "voice_manual_test.db"),
        help="SQLite path for this test (default: tests/manual/voice/voice_manual_test.db)",
    )
    p.add_argument("--debug", action="store_true", help="Debug logging")
    p.add_argument(
        "--fresh-db",
        action="store_true",
        help="Delete test DB before run so pass 1 can insert (otherwise stale DB dedupes everything)",
    )
    return p.parse_args()


def _setup_db(db_path: str) -> None:
    from wecom_automation.database.schema import init_database, run_migrations

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        init_database(str(path))
    else:
        run_migrations(str(path))


def _ensure_customer(repo, serial: str, customer_name: str, channel: str | None) -> int:
    from wecom_automation.database.models import DeviceRecord

    device = repo.get_or_create_device(serial, model="voice-manual-test")
    kefu = repo.get_or_create_kefu("VoiceManualTestKefu", device.id)
    customer = repo.get_or_create_customer(customer_name, kefu.id, channel=channel)
    return customer.id


def _count_voice_rows(conn: sqlite3.Connection, customer_id: int) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM messages WHERE customer_id = ? AND message_type = 'voice'",
        (customer_id,),
    )
    msg_n = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COUNT(*) FROM voices v
        JOIN messages m ON m.id = v.message_id
        WHERE m.customer_id = ?
        """,
        (customer_id,),
    )
    voice_n = cur.fetchone()[0]
    return msg_n, voice_n


def _sample_voice_extra_info(conn: sqlite3.Connection, customer_id: int, limit: int = 3) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, extra_info FROM messages
        WHERE customer_id = ? AND message_type = 'voice'
        ORDER BY id DESC
        LIMIT ?
        """,
        (customer_id, limit),
    )
    out: list[dict] = []
    for mid, raw in cur.fetchall():
        info: dict = {"message_id": mid}
        if raw:
            try:
                d = json.loads(raw)
                info["voice_file_path"] = d.get("voice_file_path")
                info["voice_file_size"] = d.get("voice_file_size")
                info["voice_duration"] = d.get("voice_duration")
            except json.JSONDecodeError:
                info["extra_info_parse_error"] = True
        out.append(info)
    return out


async def _run_one_pass(
    *,
    wecom,
    processor,
    context,
    voice_dir: Path,
    logger: logging.Logger,
    pass_index: int,
) -> dict:
    logger.info("")
    logger.info("=" * 60)
    logger.info("PASS %s: UI tree → parse → download voice(s) → handler", pass_index)
    logger.info("=" * 60)

    tree = await wecom.adb.get_ui_tree()
    if not tree:
        logger.error("无法获取 UI 树：请确认企业微信已打开且在聊天页")
        return {"error": "no_ui_tree"}

    messages = wecom.ui_parser.extract_conversation_messages(tree)
    voice_msgs = [m for m in messages if m.message_type == "voice"]
    logger.info("本屏共 %s 条消息，其中语音 %s 条", len(messages), len(voice_msgs))

    for i, m in enumerate(messages):
        side = "kefu" if m.is_self else "peer"
        prev = (m.content or "")[:36].replace("\n", " ")
        logger.info(
            "  [%2d] %-5s | %-6s | ts=%s | dur=%s | raw_bounds=%s | text=%r",
            i,
            side,
            m.message_type,
            m.timestamp,
            m.voice_duration,
            (m.raw_bounds or "")[:32],
            prev,
        )

    if not voice_msgs:
        logger.warning("未识别到语音消息：请把语音气泡划到可见区域，或检查 UI 解析资源 id 是否匹配当前企微版本")
        return {"error": "no_voice_on_screen", "voice_count": 0}

    voice_dir.mkdir(parents=True, exist_ok=True)
    captured_keys: set[str] = set()
    downloaded = 0
    for j, msg in enumerate(voice_msgs):
        path = await wecom._download_voice_inline(msg, voice_dir, j + 1, captured_keys)
        if path:
            msg.voice_local_path = path
            downloaded += 1
            logger.info("  语音[%d] 下载 OK -> %s", j, path)
        else:
            logger.warning("  语音[%d] 下载失败（仍将尝试入库，可能无文件路径）", j)

    added = 0
    skipped = 0
    for j, msg in enumerate(voice_msgs):
        result = await processor.process(msg, context)
        mt = result.message_type or ""
        if mt != "voice":
            logger.warning("  语音[%d] 被非 voice 处理器接管: %s", j, mt)
        if result.added:
            added += 1
            extra = result.extra or {}
            logger.info(
                "  语音[%d] 新增 message_id=%s path=%s",
                j,
                result.message_id,
                extra.get("path"),
            )
        else:
            skipped += 1
            logger.info("  语音[%d] 去重跳过 message_id=%s", j, result.message_id)

    return {
        "pass": pass_index,
        "visible_messages": len(messages),
        "voice_on_screen": len(voice_msgs),
        "voice_downloaded": downloaded,
        "voice_db_added": added,
        "voice_db_skipped": skipped,
    }


async def main_async() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logger = logging.getLogger("voice_manual_test")

    from wecom_automation.core.config import Config
    from wecom_automation.core.interfaces import MessageContext
    from wecom_automation.database.repository import ConversationRepository
    from wecom_automation.services.message.processor import create_message_processor
    from wecom_automation.services.wecom_service import WeComService

    db_path = Path(args.db)
    if args.fresh_db and db_path.exists():
        db_path.unlink()
        logger.info("Removed existing test DB (--fresh-db): %s", db_path)

    _setup_db(args.db)
    repo = ConversationRepository(args.db, auto_init=False)
    customer_id = _ensure_customer(repo, args.serial, args.customer, args.channel)

    config = Config.from_env().with_overrides(device_serial=args.serial, debug=args.debug)
    wecom = WeComService(config)

    voices_dir = _PROJECT_ROOT / "conversation_voices"
    images_dir = _PROJECT_ROOT / "conversation_images"
    videos_dir = _PROJECT_ROOT / "conversation_videos"
    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    processor = create_message_processor(
        repository=repo,
        wecom_service=wecom,
        images_dir=str(images_dir),
        videos_dir=str(videos_dir),
        voices_dir=str(voices_dir),
        logger=logger,
    )

    context = MessageContext(
        customer_id=customer_id,
        customer_name=args.customer,
        channel=args.channel,
        device_serial=args.serial,
        kefu_name="",
    )

    logger.info("DB: %s | customer_id=%s", args.db, customer_id)
    logger.info("Device: %s", args.serial)

    # 临时下载目录：与 extract 内联逻辑一致，放在 conversation_voices 下单独子目录避免混杂
    voice_scratch = voices_dir / "_manual_voice_test_scratch"
    voice_scratch.mkdir(parents=True, exist_ok=True)

    results = []
    for pass_i in (1, 2):
        r = await _run_one_pass(
            wecom=wecom,
            processor=processor,
            context=context,
            voice_dir=voice_scratch,
            logger=logger,
            pass_index=pass_i,
        )
        results.append(r)
        if r.get("error"):
            logger.error("Pass %s 中止: %s", pass_i, r)
            return 1

        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        try:
            msg_n, vox_n = _count_voice_rows(conn, customer_id)
            samples = _sample_voice_extra_info(conn, customer_id)
        finally:
            conn.close()

        logger.info(
            "Pass %s 后 DB 统计: messages.voice=%s, voices=%s",
            pass_i,
            msg_n,
            vox_n,
        )
        for s in samples:
            logger.info("  extra_info 抽样: %s", s)

    # 期望：第一轮有新增；第二轮全部跳过
    r1, r2 = results
    ok = True
    if r1.get("voice_db_added", 0) < 1:
        logger.error("预期第一轮至少新增 1 条语音消息，实际 added=%s", r1.get("voice_db_added"))
        ok = False
    if r2.get("voice_db_skipped", 0) != r2.get("voice_on_screen", 0):
        logger.error(
            "预期第二轮本屏每条语音都应去重跳过：skipped=%s voice_on_screen=%s",
            r2.get("voice_db_skipped"),
            r2.get("voice_on_screen"),
        )
        ok = False

    if ok:
        logger.info("")
        logger.info("*** 检查通过：识别 → 下载 → 入库 → voices/extra_info → 第二轮去重 ***")
    else:
        logger.warning("")
        logger.warning("*** 部分检查未通过：请根据上方日志与 DB 抽样排查 ***")

    return 0 if ok else 2


def main() -> None:
    try:
        raise SystemExit(asyncio.run(main_async()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
