#!/usr/bin/env python3
"""
Media Download Feasibility Test Script

Tests the full flow for the current chat page:
  1. Extract visible messages (no scroll)
  2. Download images via fullscreen screenshot (_download_image_via_fullscreen)
  3. Download videos via long-press save (_download_video_inline)
  4. Write all messages to the database
  5. Re-run to verify deduplication (all records should be skipped)

Prerequisites:
  - Phone is on a WeCom chat page with at least one image and one video
  - Device is connected via ADB

Usage:
    # First run (extract + store):
    python tests/manual/test_media_download.py --serial YOUR_SERIAL --customer "客户名字"

    # Second run (verify dedup - same command):
    python tests/manual/test_media_download.py --serial YOUR_SERIAL --customer "客户名字"
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configure sys.path BEFORE any project imports
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "wecom-desktop" / "backend"))


def parse_args():
    parser = argparse.ArgumentParser(description="Test media download from current chat page")
    parser.add_argument("--serial", required=True, help="ADB device serial number")
    parser.add_argument("--customer", required=True, help="Customer name (for DB record)")
    parser.add_argument(
        "--channel", default=None, help="Customer channel (optional, e.g. '企业微信')"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


async def download_image_fullscreen(wecom, msg, output_path: Path) -> bool:
    """
    Download an image message by clicking it fullscreen and taking a screenshot.
    Wraps wecom._download_image_via_fullscreen() which is a private method but
    the test accesses it directly since we ARE in the testing context.
    """
    if not msg.image or not msg.image.bounds:
        return False
    return await wecom._download_image_via_fullscreen(msg.image, output_path)


async def download_video_inline(wecom, msg, video_dir: Path, msg_index: int) -> str | None:
    """
    Download a video message via long-press save to phone, then adb pull.
    Wraps wecom._download_video_inline() directly.
    """
    captured_keys: set[str] = set()
    return await wecom._download_video_inline(msg, video_dir, msg_index, captured_keys)


async def run_extraction_and_store(args, logger):
    """Main flow: extract messages, download media, store to DB. Returns stats dict."""
    from wecom_automation.core.config import Config, get_default_db_path
    from wecom_automation.core.interfaces import MessageContext
    from wecom_automation.database.repository import ConversationRepository
    from wecom_automation.services.message.processor import MessageProcessor
    from wecom_automation.services.message.handlers.text import TextMessageHandler
    from wecom_automation.services.message.handlers.image import ImageMessageHandler
    from wecom_automation.services.message.handlers.video import VideoMessageHandler
    from wecom_automation.services.message.handlers.voice import VoiceMessageHandler
    from wecom_automation.services.message.handlers.sticker import StickerMessageHandler
    from wecom_automation.services.wecom_service import WeComService

    # ------------------------------------------------------------------
    # Init WeComService
    # ------------------------------------------------------------------
    config = Config.from_env().with_overrides(device_serial=args.serial, debug=args.debug)
    wecom = WeComService(config)

    logger.info(f"Device: {args.serial}")
    logger.info(f"Customer: {args.customer!r} / Channel: {args.channel!r}")

    # ------------------------------------------------------------------
    # Directories
    # ------------------------------------------------------------------
    images_dir = project_root / "conversation_images"
    videos_dir = project_root / "conversation_videos"
    images_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Extract visible messages from current screen
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 1: Extracting visible messages from current screen")
    logger.info("=" * 60)

    tree = await wecom.adb.get_ui_tree()
    if not tree:
        logger.error("Could not get UI tree - is WeCom open on a chat page?")
        return None

    messages = wecom.ui_parser.extract_conversation_messages(tree)
    logger.info(f"Extracted {len(messages)} messages")

    if not messages:
        logger.warning("No messages found. Check that the phone is on a WeCom chat page.")
        return None

    # Log message summary
    for i, msg in enumerate(messages):
        ts = msg.timestamp or "?"
        sender = "ME" if msg.is_self else "OTHER"
        content_preview = (msg.content or "")[:40]
        img_info = f" [image bounds={msg.image.bounds[:30] if msg.image and msg.image.bounds else 'none'}]" if msg.message_type == "image" else ""
        vid_info = f" [video duration={msg.video_duration}]" if msg.message_type == "video" else ""
        logger.info(f"  [{i:2d}] {sender} | {msg.message_type:<8} | {ts:<12} | {content_preview}{img_info}{vid_info}")

    # ------------------------------------------------------------------
    # Step 2: Download images via fullscreen
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Downloading images via fullscreen screenshot")
    logger.info("=" * 60)

    image_messages = [m for m in messages if m.message_type == "image"]
    logger.info(f"Found {len(image_messages)} image message(s)")

    timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
    downloaded_images = 0
    failed_images = 0

    for i, msg in enumerate(image_messages):
        if not msg.image or not msg.image.bounds:
            logger.warning(f"  Image [{i}]: no bounds, skipping")
            failed_images += 1
            continue

        output_path = images_dir / f"test_fullscreen_{timestamp_prefix}_{i}.png"
        logger.info(f"  Image [{i}]: bounds={msg.image.bounds} -> {output_path.name}")

        success = await download_image_fullscreen(wecom, msg, output_path)
        if success:
            size_kb = output_path.stat().st_size // 1024 if output_path.exists() else 0
            logger.info(f"    OK - saved {size_kb} KB")
            # Set local_path on the message so ImageMessageHandler uses it
            msg.image.local_path = str(output_path)
            downloaded_images += 1
        else:
            logger.warning(f"    FAILED - fullscreen download failed")
            failed_images += 1

    logger.info(f"Image download: {downloaded_images} ok, {failed_images} failed")

    # ------------------------------------------------------------------
    # Step 3: Download videos via long-press save
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 3: Downloading videos via long-press save")
    logger.info("=" * 60)

    video_messages = [m for m in messages if m.message_type == "video"]
    logger.info(f"Found {len(video_messages)} video message(s)")

    downloaded_videos = 0
    failed_videos = 0

    for i, msg in enumerate(video_messages):
        logger.info(f"  Video [{i}]: duration={msg.video_duration}, bounds={msg.raw_bounds}")

        video_path = await download_video_inline(wecom, msg, videos_dir, i)
        if video_path:
            size_kb = Path(video_path).stat().st_size // 1024 if Path(video_path).exists() else 0
            logger.info(f"    OK - saved {size_kb} KB -> {Path(video_path).name}")
            msg.video_local_path = video_path
            downloaded_videos += 1
        else:
            logger.warning(f"    FAILED - video download failed")
            failed_videos += 1

    logger.info(f"Video download: {downloaded_videos} ok, {failed_videos} failed")

    # ------------------------------------------------------------------
    # Step 4: Store all messages to database
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 4: Storing messages to database")
    logger.info("=" * 60)

    db_path = str(get_default_db_path())
    logger.info(f"Database: {db_path}")

    # Use the followup ConversationRepository to find/create customer without needing kefu_id
    from wecom_automation.database.models import CustomerRecord
    from wecom_automation.database.repository import ConversationRepository as CoreRepo

    core_repo = CoreRepo(db_path)

    # Find the customer by name in core repo; if not found, use followup repo to create
    customer_id = None
    try:
        # Try to find by name directly (without kefu_id)
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT id FROM customers WHERE name = ? LIMIT 1", (args.customer,)
            ).fetchone()
            if row:
                customer_id = row[0]
                logger.info(f"Found existing customer: id={customer_id}")
    except Exception as e:
        logger.warning(f"Customer lookup failed: {e}")

    if not customer_id:
        # Create via followup repository (handles kefu/device auto-creation)
        try:
            from services.followup.repository import ConversationRepository as FollowupRepo
            followup_repo = FollowupRepo(db_path)
            customer_id = followup_repo.find_or_create_customer(
                name=args.customer,
                channel=args.channel,
                device_serial=args.serial,
            )
            logger.info(f"Created/found customer via followup repo: id={customer_id}")
        except Exception as e:
            logger.error(f"Could not create customer: {e}")
            logger.info("Tip: Run a full initial_sync first to create the kefu/customer records,")
            logger.info("     OR pass --customer to match an existing customer name in the DB.")
            return None

    # Register handlers (same order as response_detector._register_message_handlers)
    processor = MessageProcessor(repository=core_repo, logger=logger)

    text_handler = TextMessageHandler(repository=core_repo, logger=logger)
    processor.register_handler(text_handler)

    sticker_handler = StickerMessageHandler(
        repository=core_repo,
        wecom_service=wecom,
        images_dir=images_dir,
        logger=logger,
    )
    processor.register_handler(sticker_handler)

    voice_handler = VoiceMessageHandler(
        repository=core_repo,
        voices_dir=project_root / "conversation_voices",
        logger=logger,
    )
    processor.register_handler(voice_handler)

    video_handler = VideoMessageHandler(
        repository=core_repo,
        wecom_service=wecom,
        videos_dir=videos_dir,
        logger=logger,
    )
    processor.register_handler(video_handler)

    image_handler = ImageMessageHandler(
        repository=core_repo,
        wecom_service=wecom,
        images_dir=images_dir,
        logger=logger,
    )
    processor.register_handler(image_handler)

    # Process each message
    stored_new = 0
    stored_dup = 0
    context = MessageContext(
        customer_id=customer_id,
        customer_name=args.customer,
        channel=args.channel,
        device_serial=args.serial,
        kefu_name="",
    )

    for i, msg in enumerate(messages):
        try:
            result = await processor.process(msg, context)
            if result.added:
                stored_new += 1
                logger.info(
                    f"  [{i:2d}] STORED  | {msg.message_type:<8} | id={result.message_id}"
                    + (f" | media={result.extra.get('path')}" if result.extra and result.extra.get("path") else "")
                )
            else:
                stored_dup += 1
                logger.info(f"  [{i:2d}] SKIPPED | {msg.message_type:<8} | duplicate (id={result.message_id})")
        except Exception as e:
            logger.error(f"  [{i:2d}] ERROR   | {msg.message_type:<8} | {e}")
            import traceback
            logger.debug(traceback.format_exc())

    stats = {
        "messages_extracted": len(messages),
        "images_found": len(image_messages),
        "images_downloaded": downloaded_images,
        "images_failed": failed_images,
        "videos_found": len(video_messages),
        "videos_downloaded": downloaded_videos,
        "videos_failed": failed_videos,
        "db_stored_new": stored_new,
        "db_stored_dup": stored_dup,
    }
    return stats


def print_summary(stats: dict, run_label: str, logger):
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"SUMMARY ({run_label})")
    logger.info("=" * 60)
    logger.info(f"  Messages extracted : {stats['messages_extracted']}")
    logger.info(f"  Images found       : {stats['images_found']}")
    logger.info(f"  Images downloaded  : {stats['images_downloaded']} ok, {stats['images_failed']} failed")
    logger.info(f"  Videos found       : {stats['videos_found']}")
    logger.info(f"  Videos downloaded  : {stats['videos_downloaded']} ok, {stats['videos_failed']} failed")
    logger.info(f"  DB new records     : {stats['db_stored_new']}")
    logger.info(f"  DB duplicates      : {stats['db_stored_dup']}")
    logger.info("=" * 60)


async def main():
    args = parse_args()

    from wecom_automation.core.logging import init_logging, get_logger
    init_logging(hostname="media_test", level="DEBUG" if args.debug else "INFO", console=True)
    logger = get_logger("media_download_test")

    logger.info("=" * 60)
    logger.info("Media Download Feasibility Test")
    logger.info("=" * 60)
    logger.info("Prerequisites: Phone is on a WeCom chat page")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # RUN 1: Extract + download media + store to DB
    # ------------------------------------------------------------------
    logger.info("")
    logger.info(">>> RUN 1: Extract messages and store to DB")
    logger.info("")

    stats1 = await run_extraction_and_store(args, logger)
    if stats1 is None:
        logger.error("Run 1 failed. Exiting.")
        sys.exit(1)

    print_summary(stats1, "RUN 1 - First extraction", logger)

    if stats1["db_stored_new"] == 0:
        logger.warning(
            "No new records were stored. Either all messages already exist in DB "
            "(dedup working), or extraction/storage failed."
        )

    # ------------------------------------------------------------------
    # RUN 2: Repeat extraction to verify deduplication
    # ------------------------------------------------------------------
    logger.info("")
    logger.info(">>> RUN 2: Re-extract same messages to verify deduplication")
    logger.info("    (Expected: 0 new records, all duplicates)")
    logger.info("")

    # Small pause so UI state is stable
    await asyncio.sleep(2.0)

    stats2 = await run_extraction_and_store(args, logger)
    if stats2 is None:
        logger.error("Run 2 failed.")
        sys.exit(1)

    print_summary(stats2, "RUN 2 - Dedup verification", logger)

    # ------------------------------------------------------------------
    # Final verdict
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("DEDUPLICATION VERDICT")
    logger.info("=" * 60)

    run1_new = stats1["db_stored_new"]
    run2_new = stats2["db_stored_new"]
    run2_dup = stats2["db_stored_dup"]

    if run1_new > 0 and run2_new == 0:
        logger.info(f"  PASS: Run 1 stored {run1_new} new records.")
        logger.info(f"        Run 2 correctly identified all {run2_dup} as duplicates.")
    elif run1_new == 0:
        logger.warning(
            f"  INFO: Run 1 stored 0 new records (messages may already be in DB from a previous run)."
        )
        if run2_new == 0:
            logger.info("        Run 2 also found all duplicates. Dedup is working.")
        else:
            logger.error(f"  FAIL: Run 2 stored {run2_new} NEW records after Run 1 stored 0. Something is wrong.")
    else:
        logger.error(
            f"  FAIL: Run 2 stored {run2_new} new record(s) - dedup is NOT working correctly."
        )
        logger.error("       Check compute_hash() inputs - timestamp buckets, bounds, sequence.")

    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
