"""
Phase 1: Foundation Setup

Initializes the system by:
1. Creating and validating the database
2. Testing API connections
3. Creating initial configuration
4. Setting up logging and monitoring
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

from src.database import init_db, DatabaseOperations, SessionLocal
from src.config import settings, validate_settings
from src.api_wrappers.amazon_sp_api import get_sp_api
from src.api_wrappers.keepa_api import get_keepa_api

# Use the logger configured by main.py (with UTF-8 encoding for Windows)
logger = logging.getLogger(__name__)


def setup_logging():
    """Configure logging for the system."""
    log_dir = Path(settings.log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.info("✓ Logging configured")


def setup_database():
    """Initialize the database."""
    try:
        init_db()
        logger.info("✓ Database initialized")
        return True
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        return False


def test_amazon_sp_api():
    """Test the Amazon SP-API connection."""
    try:
        sp_api = get_sp_api()
        
        # Try to get inventory summaries as a test
        logger.info("Testing Amazon SP-API connection...")
        summaries = sp_api.get_inventory_summaries()
        
        logger.info(f"✓ Amazon SP-API connection successful ({len(summaries)} products found)")
        return True
    except Exception as e:
        logger.error(f"✗ Amazon SP-API connection failed: {e}")
        return False


def test_keepa_api():
    """Test the Keepa API connection."""
    try:
        keepa_api = get_keepa_api()
        logger.info("✓ Keepa API connection successful")
        return True
    except Exception as e:
        logger.error(f"✗ Keepa API connection failed: {e}")
        return False


def validate_configuration():
    """Validate that all required configuration is present."""
    try:
        validate_settings()
        logger.info("✓ Configuration validation passed")
        return True
    except ValueError as e:
        logger.error(f"✗ Configuration validation failed: {e}")
        return False


def verify_database():
    """Verify that the database is accessible and tables exist."""
    try:
        session = SessionLocal()

        from src.database import Product
        products = session.query(Product).count()
        logger.info(f"✓ Database verified ({products} products in DB)")
        return True
    except Exception as e:
        logger.error(f"✗ Database verification failed: {e}")
        return False
    finally:
        session.close()


def print_system_status():
    """Print a summary of the system status."""
    print("\n" + "=" * 70)
    print("AMAZON REPLENS AUTOMATION SYSTEM - SETUP COMPLETE")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Database Type: {settings.database_type}")
    print(f"  Database URL: {settings.database_url}")
    print(f"  Amazon Region: {settings.amazon_region}")
    print(f"  Min Profit Margin: {settings.min_profit_margin * 100}%")
    print(f"  Min ROI: {settings.min_roi * 100}%")
    print(f"  Target Buy Box Win Rate: {settings.target_buy_box_win_rate * 100}%")
    print(f"\nNext Steps:")
    print(f"  1. Review and customize configuration in .env file")
    print(f"  2. Run Auto Discovery: uv run python -m src.phases.phase_2_auto_discovery --max 50")
    print(f"  3. Run Supplier Sourcing: uv run python -m src.phases.phase_3_sourcing_google")
    print(f"  4. Start the dashboard: uv run streamlit run src/dashboard/app.py")
    print("=" * 70 + "\n")


def main():
    """Run the Phase 1 setup."""
    logger.info("Starting Phase 1: Foundation Setup")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    
    # Step 1: Setup logging
    logger.info("\n[1/6] Setting up logging...")
    setup_logging()
    
    # Step 2: Validate configuration
    logger.info("\n[2/6] Validating configuration...")
    if not validate_configuration():
        logger.error("Configuration validation failed. Please check your .env file.")
        return False
    
    # Step 3: Initialize database
    logger.info("\n[3/6] Initializing database...")
    if not setup_database():
        logger.error("Database initialization failed.")
        return False
    
    # Step 4: Test Amazon SP-API
    logger.info("\n[4/6] Testing Amazon SP-API connection...")
    sp_api_ok = test_amazon_sp_api()
    
    # Step 5: Test Keepa API
    logger.info("\n[5/6] Testing Keepa API connection...")
    keepa_api_ok = test_keepa_api()
    
    # Step 6: Verify database access
    logger.info("\n[6/6] Verifying database...")
    verify_database()
    
    # Print status
    logger.info("\n" + "=" * 70)
    logger.info("PHASE 1 SETUP COMPLETE")
    logger.info("=" * 70)
    
    if sp_api_ok and keepa_api_ok:
        logger.info("✓ All systems operational")
        print_system_status()
        return True
    else:
        logger.warning("⚠ Some API connections failed. Check configuration and try again.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
