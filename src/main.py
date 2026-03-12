"""
Main entry point for the Amazon Replens Automation System.

Orchestrates all 5 phases sequentially:
  Phase 1: Foundation Setup (DB init, API validation)
  Phase 2: Product Discovery (Keepa analysis, ML scoring)
  Phase 3: Supplier Sourcing (Google Custom Search)
  Phase 4: Dynamic Repricing (competitor monitoring, price optimization)
  Phase 5: Inventory Forecasting (demand prediction, reorder alerts)

Usage:
  uv run python -m src.main                    # Run all phases
  uv run python -m src.main --skip 1 3         # Skip phases 1 and 3
  uv run python -m src.main --only 4           # Run only phase 4
  uv run python -m src.main --apply-repricing   # Phase 4 in live mode
"""

import argparse
import logging
import sys

from src.phases import (
    phase_1_setup,
    phase_2_auto_discovery,
    phase_3_sourcing_google,
    phase_4_repricing,
    phase_5_forecasting,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_phase_1():
    """Phase 1: Foundation Setup."""
    logger.info("\n--- Phase 1: Foundation Setup ---")
    if not phase_1_setup.main():
        logger.error("Phase 1 failed. Aborting.")
        return False
    return True


def run_phase_2():
    """Phase 2: Auto Product Discovery."""
    logger.info("\n--- Phase 2: Auto Product Discovery ---")
    try:
        engine = phase_2_auto_discovery.AutoDiscoveryEngine()
        stats = engine.run_with_keywords(
            keywords=[
                'violin accessories',
                'guitar accessories',
                'music instrument care',
                'violin rosin',
                'instrument strings',
            ],
            max_products=50,
        )
        if stats['opportunities'] == 0:
            logger.warning("Phase 2 found no opportunities. Continuing anyway.")
        return True
    except Exception as e:
        logger.error(f"Phase 2 failed: {e}")
        return False


def run_phase_3():
    """Phase 3: Supplier Sourcing."""
    logger.info("\n--- Phase 3: Sourcing & Procurement ---")
    try:
        phase_3_sourcing_google.main()
        return True
    except Exception as e:
        logger.error(f"Phase 3 failed: {e}")
        return False


def run_phase_4(apply: bool = False):
    """Phase 4: Dynamic Repricing."""
    mode = "LIVE" if apply else "DRY-RUN"
    logger.info(f"\n--- Phase 4: Dynamic Repricing ({mode}) ---")
    try:
        engine = phase_4_repricing.RepricingEngine(dry_run=not apply)
        stats = engine.run()
        if stats['products_processed'] == 0:
            logger.info("Phase 4: No products with real costs to reprice.")
            logger.info("  Add costs: uv run python tools/manage_suppliers.py export")
        return True
    except Exception as e:
        logger.error(f"Phase 4 failed: {e}")
        return False


def run_phase_5():
    """Phase 5: Inventory Forecasting."""
    logger.info("\n--- Phase 5: Inventory Forecasting ---")
    try:
        engine = phase_5_forecasting.ForecastingEngine()
        engine.run()
        return True
    except Exception as e:
        logger.error(f"Phase 5 failed: {e}")
        return False


def main():
    """Run all phases of the Replens automation system."""
    parser = argparse.ArgumentParser(description="Amazon Replens Automation System")
    parser.add_argument("--skip", nargs="+", type=int, default=[],
                        help="Phase numbers to skip (e.g., --skip 1 3)")
    parser.add_argument("--only", nargs="+", type=int, default=[],
                        help="Run only these phases (e.g., --only 4 5)")
    parser.add_argument("--apply-repricing", action="store_true",
                        help="Apply Phase 4 repricing changes (default: dry-run)")
    args = parser.parse_args()

    phases_to_run = set(args.only) if args.only else {1, 2, 3, 4, 5}
    phases_to_run -= set(args.skip)

    logger.info("Starting Amazon Replens Automation System")
    logger.info(f"Running phases: {sorted(phases_to_run)}")

    phase_runners = {
        1: run_phase_1,
        2: run_phase_2,
        3: run_phase_3,
        4: lambda: run_phase_4(apply=args.apply_repricing),
        5: run_phase_5,
    }

    failed = []
    for phase_num in sorted(phases_to_run):
        runner = phase_runners.get(phase_num)
        if runner:
            success = runner()
            if not success:
                failed.append(phase_num)
                if phase_num == 1:
                    logger.error("Phase 1 (setup) failed — aborting remaining phases.")
                    break
                logger.warning(f"Phase {phase_num} failed. Continuing with remaining phases.")

    if failed:
        logger.warning(f"\nCompleted with failures in phase(s): {failed}")
    else:
        logger.info("\nAll phases completed successfully!")


if __name__ == "__main__":
    main()
