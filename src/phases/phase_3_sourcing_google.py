"""
Phase 3: Supplier Matching with Google Shopping API

Finds suppliers using Google Custom Search API.
Searches B2B platforms like Alibaba, Global Sources, Made-in-China, etc.
"""

import logging
import sys
from datetime import datetime
from typing import List, Dict, Any
from decimal import Decimal

from src.database import SessionLocal, Product, Supplier, ProductSupplier, DatabaseOperations
from src.api_wrappers.google_shopping_finder import get_google_shopping_finder
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class GoogleSupplierMatchingEngine:
    """
    Uses Google Custom Search API to find and match suppliers to products.
    """

    def __init__(self, use_google: bool = True):
        """Initialize the engine."""
        self.session = SessionLocal()
        self.db = DatabaseOperations()
        self.use_google = use_google

        if use_google:
            try:
                self.google_finder = get_google_shopping_finder()
                logger.info("✓ Google Shopping finder initialized")
            except Exception as e:
                logger.warning(f"⚠ Google Shopping not available: {e}")
                logger.info("  Falling back to demo suppliers")
                self.use_google = False

    def discover_suppliers_for_product(self, product: Product) -> Dict[str, Any]:
        """
        Use Google to discover suppliers for a product.

        Args:
            product: Product to find suppliers for

        Returns:
            Supplier discovery results
        """
        logger.info(f"Finding suppliers for: {product.title}")

        if not self.use_google:
            return self._get_demo_suppliers()

        try:
            # Use Google to find suppliers
            result = self.google_finder.search_multiple_platforms(product.title)

            # Check for quota exceeded
            if result.get('quota_exceeded'):
                return {'all_suppliers': [], 'quota_exceeded': True}

            logger.info(f"✓ Google found {len(result.get('all_suppliers', []))} supplier listings")
            alibaba_count = len(result.get('alibaba', []))
            gs_count = len(result.get('global_sources', []))
            other_count = len(result.get('other', []))
            logger.info(f"  Alibaba: {alibaba_count}, Global Sources: {gs_count}, Other: {other_count}")

            return result

        except Exception as e:
            logger.error(f"✗ Error with Google discovery: {e}")
            return self._get_demo_suppliers()

    def create_suppliers_from_google(self, discovery_result: Dict[str, Any]) -> List[Supplier]:
        """
        Create supplier records from Google search results.
        Includes both B2B manufacturers and retail/wholesale distributors.

        Args:
            discovery_result: Results from Google Shopping finder

        Returns:
            List of created suppliers
        """
        suppliers = []
        all_suppliers = discovery_result.get('all_suppliers', [])

        for supplier_info in all_suppliers:
            platform = supplier_info.get('platform', 'Unknown')
            name = supplier_info.get('name', 'Unknown Supplier')
            url = supplier_info.get('url', '')
            supplier_type = supplier_info.get('supplier_type', 'wholesaler')

            # Skip if no URL
            if not url:
                logger.warning(f"  ✗ Skipping supplier with no URL: {name}")
                continue

            # Check if supplier already exists (by URL to avoid duplicates)
            existing = self.session.query(Supplier).filter(
                Supplier.website == url
            ).first()

            if existing:
                suppliers.append(existing)
                continue

            # No hardcoded data - all values set to defaults
            # User must manually check supplier page for actual prices/MOQ
            moq = None  # Unknown - check supplier page
            lead_time = None  # Unknown - check supplier page
            reliability = None  # Unknown

            # Create supplier - no hardcoded data, user must check manually
            supplier = Supplier(
                name=f"{platform} - {name[:50]}",
                website=url,
                min_order_qty=0,  # Unknown - check supplier page
                lead_time_days=0,  # Unknown - check supplier page
                reliability_score=0.0,  # Unknown
                on_time_delivery_rate=0.0,  # Unknown
                status='active',
                notes=f"Type: {supplier_type.upper()}. Discovered via Google. CHECK SUPPLIER PAGE FOR ACTUAL PRICES/MOQ. {supplier_info.get('description', '')[:150]}"
            )

            self.session.add(supplier)
            suppliers.append(supplier)
            logger.info(f"  ✓ Found {supplier_type}: {supplier.name[:50]} - {url[:60]}")

        self.session.commit()
        return suppliers

    def match_product_to_suppliers(self, product: Product, suppliers: List[Supplier]) -> List[ProductSupplier]:
        """
        Link product to discovered suppliers.

        NO HARDCODED DATA - all cost/profit fields are set to 0.
        User must manually check supplier pages and update costs.

        Args:
            product: Product to match
            suppliers: Available suppliers

        Returns:
            List of product-supplier matches
        """
        matches = []

        for supplier in suppliers:
            # Determine supplier type from notes
            supplier_notes = supplier.notes or ''
            if 'Type: MANUFACTURER' in supplier_notes:
                supplier_type = 'Manufacturer'
            elif 'Type: RETAILER' in supplier_notes:
                supplier_type = 'Retailer'
            else:
                supplier_type = 'Wholesaler'

            # Check if match already exists
            existing = self.session.query(ProductSupplier).filter(
                ProductSupplier.asin == product.asin,
                ProductSupplier.supplier_id == supplier.supplier_id
            ).first()

            if existing:
                # Already linked, skip
                matches.append(existing)
                continue

            # Create product-supplier link with NO estimated data
            # All values = 0 means "not yet checked"
            match = ProductSupplier(
                asin=product.asin,
                supplier_id=supplier.supplier_id,
                supplier_cost=Decimal('0'),      # Unknown - check supplier page
                shipping_cost=Decimal('0'),      # Unknown - check supplier page
                total_cost=Decimal('0'),         # Unknown - check supplier page
                estimated_profit=Decimal('0'),   # Unknown - calculate after checking
                profit_margin=0.0,               # Unknown - calculate after checking
                roi=0.0,                         # Unknown - calculate after checking
            )
            self.session.add(match)
            matches.append(match)

            logger.info(f"  ✓ Linked {supplier_type}: {supplier.name[:50]}")
            logger.info(f"    → {supplier.website[:70]}")

        # No preferred supplier auto-selection - user decides after checking prices
        self.session.commit()
        return matches

    def _get_demo_suppliers(self) -> Dict[str, Any]:
        """Fallback suppliers when Google API is unavailable."""
        logger.warning("Google API not configured — using fallback supplier platforms.")
        logger.warning("Configure GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID in .env for real supplier discovery.")
        return {
            'all_suppliers': [
                {
                    'platform': 'Alibaba',
                    'name': 'Alibaba Wholesale Marketplace',
                    'url': 'https://www.alibaba.com',
                    'supplier_type': 'wholesaler',
                    'description': 'B2B wholesale marketplace — search for products manually. Google API not configured for automated search.'
                },
                {
                    'platform': 'Global Sources',
                    'name': 'Global Sources Trade Platform',
                    'url': 'https://www.globalsources.com',
                    'supplier_type': 'wholesaler',
                    'description': 'B2B trade platform — search for products manually. Google API not configured for automated search.'
                }
            ]
        }

    def run(self, limit: int = 50) -> Dict[str, int]:
        """
        Run the Google-powered supplier matching.

        Args:
            limit: Max products to process

        Returns:
            Statistics
        """
        logger.info("Starting Google Supplier Matching Engine")
        logger.info(f"Google enabled: {self.use_google}")

        # Get products
        products = self.db.get_underserved_products(self.session, limit=limit)
        logger.info(f"Found {len(products)} products to analyze")

        total_matches = 0
        products_matched = 0

        for i, product in enumerate(products):
            logger.info(f"\n{'='*60}")
            logger.info(f"Product {i+1}/{len(products)}: {product.title}")
            logger.info(f"ASIN: {product.asin}")

            # Rate limiting: wait between products to avoid 429 errors
            # Google allows ~100 free queries/day, so be conservative
            if i > 0 and self.use_google:
                import time
                delay = 2  # 2 seconds between products
                logger.debug(f"Rate limiting: waiting {delay}s...")
                time.sleep(delay)

            # Discover suppliers using Google
            discovery_result = self.discover_suppliers_for_product(product)

            # Check for rate limiting
            if discovery_result.get('quota_exceeded'):
                logger.error(f"⚠ Google API quota exceeded. Stopping to preserve remaining quota.")
                logger.error(f"  Processed {i+1} of {len(products)} products before hitting limit.")
                logger.error(f"  Wait until tomorrow or upgrade your Google API plan.")
                break

            # Create supplier records
            suppliers = self.create_suppliers_from_google(discovery_result)

            # Match product to suppliers
            matches = self.match_product_to_suppliers(product, suppliers)

            if matches:
                total_matches += len(matches)
                products_matched += 1
                logger.info(f"✓ Linked {len(matches)} suppliers (check pages for actual prices)")

        logger.info(f"\n{'='*60}")
        logger.info("PHASE 3 COMPLETE - Supplier Discovery")
        logger.info(f"{'='*60}")
        logger.info(f"Products processed: {products_matched}")
        logger.info(f"Supplier links found: {total_matches}")
        logger.info(f"")
        logger.info(f"NEXT STEPS:")
        logger.info(f"  1. View suppliers in dashboard: uv run streamlit run src/dashboard/app.py")
        logger.info(f"  2. Click supplier links to check actual prices")
        logger.info(f"  3. Update costs in database after checking")
        logger.info(f"{'='*60}")

        return {
            'products_matched': products_matched,
            'total_matches': total_matches
        }


def main():
    """Run Phase 3 with Google Shopping API."""
    try:
        # Check if Google is configured
        use_google = bool(settings.google_api_key and settings.google_search_engine_id)

        if not use_google:
            logger.warning("⚠ Google API not configured")
            logger.info("  Add GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID to .env")
            logger.info("  Running with demo suppliers instead...")

        engine = GoogleSupplierMatchingEngine(use_google=use_google)
        stats = engine.run()

        logger.info(f"\n✓ Phase 3 complete!")
        return True

    except Exception as e:
        logger.error(f"✗ Phase 3 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
