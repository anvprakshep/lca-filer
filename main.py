# main.py
import asyncio
import argparse
import os
import sys
from typing import Dict, Any, List, Optional

from lca_filer import LCAFiler
from utils.file_utils import FileUtils
from utils.logger import get_logger

logger = get_logger("main")


async def main() -> int:
    """
    Main entry point for LCA filing automation.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Automate H-1B LCA filing on DOL FLAG portal")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--input", help="Path to input CSV file with application data")
    parser.add_argument("--sample", action="store_true", help="Create a sample CSV file")
    parser.add_argument("--sample-output", default="sample_h1b_applications.csv", help="Path for sample CSV output")
    parser.add_argument("--batch-size", type=int, default=None, help="Process only a subset of applications")
    args = parser.parse_args()

    # Create sample CSV if requested
    if args.sample:
        logger.info(f"Creating sample CSV file at {args.sample_output}")
        if FileUtils.create_sample_csv(args.sample_output):
            logger.info(f"Sample CSV created successfully at {args.sample_output}")
            return 0
        else:
            logger.error("Failed to create sample CSV")
            return 1

    # Check for input file
    if not args.input:
        logger.error("No input file specified. Use --input to specify a CSV file or --sample to create a sample.")
        return 1

    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return 1

    # Load applications from CSV
    applications = FileUtils.load_applications_from_csv(args.input)

    if not applications:
        logger.error(f"No valid applications found in {args.input}")
        return 1

    # Apply batch size if specified
    if args.batch_size and args.batch_size > 0:
        applications = applications[:args.batch_size]
        logger.info(f"Processing first {args.batch_size} applications")

    print("Initializing...")

    # Initialize LCA filer
    lca_filer = LCAFiler(args.config)

    try:
        # Initialize components
        logger.info("Initializing LCA filer")
        if not await lca_filer.initialize():
            logger.error("Failed to initialize LCA filer")
            return 1

        # Process applications
        logger.info(f"Processing {len(applications)} applications")
        results = await lca_filer.process_batch(applications)

        # Log results summary
        success_count = sum(1 for r in results if r.get("status") == "success")
        error_count = sum(1 for r in results if r.get("status") in ["error", "validation_failed", "submission_failed"])
        other_count = len(results) - success_count - error_count

        logger.info(
            f"Processing complete. Results: {success_count} successful, {error_count} failed, {other_count} other")

        return 0

    except Exception as e:
        logger.error(f"Error in main process: {str(e)}")
        return 1

    finally:
        # Clean up resources
        logger.info("Shutting down LCA filer")
        await lca_filer.shutdown()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        sys.exit(1)