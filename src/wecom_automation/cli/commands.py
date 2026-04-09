"""
CLI commands for WeCom Automation.

This module provides the main entry points for command-line usage.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from wecom_automation import __version__
from wecom_automation.core.config import Config
from wecom_automation.core.logging import setup_logger
from wecom_automation.services.wecom_service import WeComService


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="wecom-automation",
        description="WeCom Automation - Extract Private Chat users from WeCom",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full workflow (launch, switch to private chats, extract users)
  wecom-automation

  # Skip launch if WeCom is already open
  wecom-automation --skip-launch

  # Extract with avatar screenshots
  wecom-automation --skip-launch --capture-avatars --output-dir ./output

  # Export results to JSON
  wecom-automation --skip-launch --output-json users.json

  # Debug mode with full logging
  wecom-automation --debug --log-file debug.log
        """,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Device options
    device_group = parser.add_argument_group("Device Options")
    device_group.add_argument(
        "--serial",
        help="ADB serial of the target device (omit when only one device connected)",
    )
    device_group.add_argument(
        "--prefer-tcp",
        action="store_true",
        help="Prefer TCP bridge for faster reads",
    )

    # Workflow options
    workflow_group = parser.add_argument_group("Workflow Options")
    workflow_group.add_argument(
        "--skip-launch",
        action="store_true",
        help="Skip launching WeCom (assumes app is already open)",
    )
    workflow_group.add_argument(
        "--wait-after-launch",
        type=float,
        default=3.0,
        help="Seconds to wait after launching WeCom (default: 3.0)",
    )

    # Extraction options
    extract_group = parser.add_argument_group("Extraction Options")
    extract_group.add_argument(
        "--max-scrolls",
        type=int,
        default=20,
        help="Maximum number of scroll attempts (default: 20)",
    )
    extract_group.add_argument(
        "--scroll-delay",
        type=float,
        default=1.0,
        help="Delay between scrolls in seconds (default: 1.0)",
    )
    extract_group.add_argument(
        "--stable-threshold",
        type=int,
        default=2,
        help="Stop after N scrolls with no new entries (default: 2)",
    )

    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output-json",
        type=str,
        metavar="FILE",
        help="Export results to JSON file",
    )
    output_group.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Directory for output files (default: current directory)",
    )
    output_group.add_argument(
        "--capture-avatars",
        action="store_true",
        help="Capture screenshots of avatar images",
    )

    # Logging options
    logging_group = parser.add_argument_group("Logging Options")
    logging_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging (verbose)",
    )
    logging_group.add_argument(
        "--log-file",
        type=str,
        metavar="FILE",
        help="Write logs to file",
    )

    return parser


def build_config(args: argparse.Namespace) -> Config:
    """Build configuration from command-line arguments."""
    from wecom_automation.core.config import ScrollConfig, TimingConfig

    timing = TimingConfig(
        wait_after_launch=args.wait_after_launch,
        scroll_delay=args.scroll_delay,
    )

    scroll = ScrollConfig(
        max_scrolls=args.max_scrolls,
        stable_threshold=args.stable_threshold,
    )

    return Config(
        timing=timing,
        scroll=scroll,
        device_serial=args.serial,
        use_tcp=args.prefer_tcp,
        debug=args.debug,
        log_file=args.log_file,
        output_dir=args.output_dir,
        capture_avatars=args.capture_avatars,
    )


async def run_workflow(args: argparse.Namespace) -> int:
    """
    Run the automation workflow.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Setup logging
    logger = setup_logger(
        name="wecom_automation",
        debug=args.debug,
        log_file=args.log_file,
    )

    logger.info("=" * 60)
    logger.info("WeCom Automation - Private Chat User Extraction")
    logger.info("=" * 60)
    logger.info(f"Version: {__version__}")
    logger.info(f"Started at: {datetime.now().isoformat()}")

    # Build configuration
    config = build_config(args)

    # Create service and run workflow
    service = WeComService(config)

    try:
        result = await service.run_full_workflow(
            skip_launch=args.skip_launch,
            capture_avatars=args.capture_avatars,
            output_dir=args.output_dir,
        )

        if not result.success:
            logger.error(f"Workflow failed: {result.error_message}")
            return 1

        # Display results
        print("\n" + "=" * 60)
        print(f"EXTRACTION RESULTS - {result.total_count} Users Found")
        print("=" * 60)
        print(result.format_table())

        # Export to JSON if requested
        if args.output_json:
            output_path = Path(args.output_json)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"\nResults exported to: {output_path}")
            logger.info(f"Results exported to: {output_path}")

        # Summary
        print(f"\nExtraction completed in {result.duration_seconds:.1f}s")
        print(f"Total scrolls: {result.total_scrolls}")

        logger.info(f"Completed at: {datetime.now().isoformat()}")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        return 1


def main() -> None:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    exit_code = asyncio.run(run_workflow(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
