"""
Temporary runner for test_media_download.py
Usage: python tests/manual/_run_media_test.py
"""
import sys
import asyncio
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "wecom-desktop" / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


class Args:
    serial = "320125365403"
    customer = "\u5b59\u5fb7\u5bb6 (\u82cf\u5357\u8001\u5e08\uff0812\uff0d21\u70b9\u5728\u7ebf\uff0c\u6709\u4e8b\u7535\u8bdd\u8054\u7cfb\uff09)"
    channel = None
    debug = False


from wecom_automation.core.logging import init_logging, get_logger
from test_media_download import run_extraction_and_store, print_summary


async def main():
    init_logging(hostname="media_test", level="INFO", console=True)
    logger = get_logger("media_download_test")

    logger.info("=" * 60)
    logger.info("Media Download Feasibility Test")
    logger.info(f"Device  : {Args.serial}")
    logger.info(f"Customer: {Args.customer}")
    logger.info("=" * 60)

    # RUN 1
    logger.info("")
    logger.info(">>> RUN 1: Extract messages and store to DB")
    stats1 = await run_extraction_and_store(Args, logger)
    if not stats1:
        logger.error("Run 1 failed")
        return

    print_summary(stats1, "RUN 1 - First extraction", logger)

    # RUN 2 - dedup verification
    logger.info("")
    logger.info(">>> RUN 2: Re-extract to verify deduplication")
    await asyncio.sleep(2)
    stats2 = await run_extraction_and_store(Args, logger)
    if not stats2:
        logger.error("Run 2 failed")
        return

    print_summary(stats2, "RUN 2 - Dedup verification", logger)

    logger.info("")
    logger.info("=" * 60)
    logger.info("DEDUPLICATION VERDICT")
    logger.info("=" * 60)
    if stats2["db_stored_new"] == 0:
        logger.info(f"  PASS: Run 1 stored {stats1['db_stored_new']} new records.")
        logger.info(f"        Run 2 correctly identified all {stats2['db_stored_dup']} as duplicates.")
    else:
        logger.error(f"  FAIL: Run 2 stored {stats2['db_stored_new']} new records (should be 0).")


asyncio.run(main())
