"""
Main entry point for the Amazon Replens Automation System.

This script orchestrates the execution of all phases of the system.
"""

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

def main():
    """Run all phases of the Replens automation system."""
    logger.info("Starting Amazon Replens Automation System")

    # Phase 1: Foundation Setup
    logger.info("\n--- Running Phase 1: Foundation Setup ---")
    if not phase_1_setup.main():
        logger.error("Phase 1 failed. Aborting.")
        sys.exit(1)

    # Phase 2: Auto Product Discovery
    logger.info("\n--- Running Phase 2: Auto Product Discovery ---")
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

    # Phase 3: Sourcing & Procurement
    logger.info("\n--- Running Phase 3: Sourcing & Procurement ---")
    phase_3_sourcing_google.main()

    # Phase 4: Dynamic Repricing
    logger.info("\n--- Running Phase 4: Dynamic Repricing ---")
    phase_4_repricing.main()

    # Phase 5: Inventory Forecasting
    logger.info("\n--- Running Phase 5: Inventory Forecasting ---")
    phase_5_forecasting.main()

    logger.info("\n✓ All phases completed successfully!")

if __name__ == "__main__":
    main()
