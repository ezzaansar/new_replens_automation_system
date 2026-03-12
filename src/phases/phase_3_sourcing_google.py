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
from src.config import (
    settings, AMAZON_REFERRAL_FEES, AMAZON_FBA_FEE_DEFAULT,
    WHOLESALE_COST_RATIOS, ESTIMATED_SHIPPING_COSTS,
)

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

    def create_suppliers_from_google(self, discovery_result: Dict[str, Any]) -> tuple:
        """
        Create supplier records from Google search results.

        Args:
            discovery_result: Results from Google Shopping finder

        Returns:
            Tuple of (supplier ORM objects, raw supplier info dicts)
        """
        suppliers = []
        supplier_infos = []
        all_suppliers = discovery_result.get('all_suppliers', [])

        for supplier_info in all_suppliers:
            platform = supplier_info.get('platform', 'Unknown')
            name = supplier_info.get('name', 'Unknown Supplier')
            url = supplier_info.get('url', '')
            supplier_type = supplier_info.get('supplier_type', 'wholesaler')

            if not url:
                logger.warning(f"  ✗ Skipping supplier with no URL: {name}")
                continue

            # Check if supplier already exists (by URL to avoid duplicates)
            existing = self.session.query(Supplier).filter(
                Supplier.website == url
            ).first()

            if existing:
                suppliers.append(existing)
                supplier_infos.append(supplier_info)
                continue

            # Estimate lead time by platform
            if platform.lower() in ('alibaba', 'made-in-china', 'dhgate'):
                est_lead_time = 14  # ~2 weeks from China
            elif platform.lower() in ('global sources', 'tradekey', 'indiamart'):
                est_lead_time = 14
            else:
                est_lead_time = 7

            # Extract MOQ from price data if available
            price_data = supplier_info.get('price_data', {}) or {}
            est_moq = price_data.get('moq', 50)  # Default MOQ 50

            supplier = Supplier(
                name=f"{platform} - {name[:50]}",
                website=url,
                min_order_qty=est_moq,
                lead_time_days=est_lead_time,
                reliability_score=50.0,  # Neutral starting score
                on_time_delivery_rate=0.85,  # Conservative estimate
                status='active',
                notes=f"Type: {supplier_type.upper()}. Auto-discovered via Google. {supplier_info.get('description', '')[:150]}"
            )

            self.session.add(supplier)
            suppliers.append(supplier)
            supplier_infos.append(supplier_info)
            logger.info(f"  ✓ Found {supplier_type}: {supplier.name[:50]} - {url[:60]}")

        self.session.commit()
        return suppliers, supplier_infos

    def _estimate_supplier_cost(self, product: Product, supplier_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Auto-estimate supplier cost from available data.

        Priority:
        1. Price extracted from Google snippet (Alibaba listings show prices)
        2. Category-based wholesale ratio (typical B2B margin)

        Args:
            product: Product with Amazon price
            supplier_info: Supplier data including price_data from Google

        Returns:
            Dict with supplier_cost, shipping_cost, total_cost, source
        """
        amazon_price = float(product.current_price or 0)
        if amazon_price <= 0:
            return {'supplier_cost': Decimal('0'), 'shipping_cost': Decimal('0'),
                    'total_cost': Decimal('0'), 'source': 'none'}

        category = (product.category or '').strip()
        cat_lower = category.lower()

        # Determine shipping cost based on supplier platform
        platform = (supplier_info.get('platform', '') or '').lower()
        if platform in ('alibaba', 'made-in-china', 'dhgate'):
            shipping = ESTIMATED_SHIPPING_COSTS['china_standard']
        elif platform in ('global sources', 'tradekey', 'indiamart'):
            shipping = ESTIMATED_SHIPPING_COSTS['china_standard']
        else:
            shipping = ESTIMATED_SHIPPING_COSTS['default']

        # Method 1: Use price from Google snippet if available
        price_data = supplier_info.get('price_data')
        if price_data and price_data.get('min_price'):
            # Use midpoint of price range
            min_p = price_data['min_price']
            max_p = price_data.get('max_price', min_p)
            unit_cost_usd = (min_p + max_p) / 2

            # Convert USD to GBP (approximate rate)
            currency = price_data.get('currency', 'USD')
            if currency == 'USD':
                unit_cost_gbp = unit_cost_usd * 0.79  # USD → GBP
            else:
                unit_cost_gbp = unit_cost_usd  # Already GBP

            # Sanity check: cost should be < 60% of Amazon price
            if unit_cost_gbp < amazon_price * 0.60:
                supplier_cost = Decimal(str(round(unit_cost_gbp, 2)))
                total_cost = supplier_cost + shipping
                return {
                    'supplier_cost': supplier_cost,
                    'shipping_cost': shipping,
                    'total_cost': total_cost,
                    'source': 'extracted',
                    'moq': price_data.get('moq'),
                }
            else:
                logger.info(f"  Extracted price £{unit_cost_gbp:.2f} rejected "
                            f"(≥60% of Amazon price £{amazon_price:.2f}), "
                            f"falling back to category ratio")

        # Method 2: Category-based wholesale estimation
        # Try exact match first, then title-case, then default
        ratio = WHOLESALE_COST_RATIOS.get(category,
                WHOLESALE_COST_RATIOS.get(category.title(),
                WHOLESALE_COST_RATIOS['default']))

        estimated_cost = round(amazon_price * ratio, 2)
        supplier_cost = Decimal(str(estimated_cost))
        total_cost = supplier_cost + shipping

        return {
            'supplier_cost': supplier_cost,
            'shipping_cost': shipping,
            'total_cost': total_cost,
            'source': 'estimated',
        }

    def _calculate_profitability(self, amazon_price: float, total_cost: Decimal,
                                  category: str) -> Dict[str, Any]:
        """
        Calculate profitability metrics for a product-supplier pair.

        Args:
            amazon_price: Current Amazon selling price
            total_cost: Total landed cost (supplier + shipping)
            category: Product category for fee calculation

        Returns:
            Dict with estimated_profit, profit_margin, roi
        """
        price = Decimal(str(amazon_price))
        if price <= 0 or total_cost <= 0:
            return {'estimated_profit': Decimal('0'), 'profit_margin': 0.0, 'roi': 0.0}

        # Calculate Amazon fees
        cat_lower = (category or '').lower().strip()
        referral_rate = Decimal(str(
            AMAZON_REFERRAL_FEES.get(cat_lower, AMAZON_REFERRAL_FEES['default'])
        ))
        referral_fee = price * referral_rate
        fba_fee = AMAZON_FBA_FEE_DEFAULT
        total_fees = referral_fee + fba_fee

        # Net profit = price - cost - fees
        net_profit = price - total_cost - total_fees
        profit_margin = float(net_profit / price) if price > 0 else 0.0
        roi = float(net_profit / total_cost) if total_cost > 0 else 0.0

        return {
            'estimated_profit': net_profit.quantize(Decimal('0.01')),
            'profit_margin': round(profit_margin, 4),
            'roi': round(roi, 4),
        }

    def match_product_to_suppliers(self, product: Product, suppliers: List[Supplier],
                                    supplier_infos: List[Dict[str, Any]] = None) -> List[ProductSupplier]:
        """
        Link product to discovered suppliers with auto-estimated costs.

        Costs are estimated from:
        1. Prices extracted from Google snippets (Alibaba often shows unit prices)
        2. Category-based wholesale ratios (25-40% of retail)

        Args:
            product: Product to match
            suppliers: Supplier ORM objects
            supplier_infos: Raw supplier dicts from Google (with price_data)

        Returns:
            List of product-supplier matches
        """
        matches = []
        best_margin = -999
        best_match = None

        for i, supplier in enumerate(suppliers):
            # Get raw supplier info for price extraction
            info = supplier_infos[i] if supplier_infos and i < len(supplier_infos) else {}

            # Check if match already exists
            existing = self.session.query(ProductSupplier).filter(
                ProductSupplier.asin == product.asin,
                ProductSupplier.supplier_id == supplier.supplier_id
            ).first()

            if existing:
                # Update costs if they were previously zero
                if existing.supplier_cost <= 0:
                    cost_data = self._estimate_supplier_cost(product, info)
                    if cost_data['total_cost'] > 0:
                        amazon_price = float(product.current_price or 0)
                        prof = self._calculate_profitability(
                            amazon_price, cost_data['total_cost'], product.category or '')
                        existing.supplier_cost = cost_data['supplier_cost']
                        existing.shipping_cost = cost_data['shipping_cost']
                        existing.total_cost = cost_data['total_cost']
                        existing.estimated_profit = prof['estimated_profit']
                        existing.profit_margin = prof['profit_margin']
                        existing.roi = prof['roi']
                        src = cost_data['source']
                        logger.info(f"  ↻ Updated costs for existing link ({src}): "
                                    f"cost=£{cost_data['total_cost']}, margin={prof['profit_margin']:.0%}")
                matches.append(existing)
                if existing.profit_margin and existing.profit_margin > best_margin:
                    best_margin = existing.profit_margin
                    best_match = existing
                continue

            # Estimate costs automatically
            cost_data = self._estimate_supplier_cost(product, info)
            amazon_price = float(product.current_price or 0)
            prof = self._calculate_profitability(
                amazon_price, cost_data['total_cost'], product.category or '')

            match = ProductSupplier(
                asin=product.asin,
                supplier_id=supplier.supplier_id,
                supplier_cost=cost_data['supplier_cost'],
                shipping_cost=cost_data['shipping_cost'],
                total_cost=cost_data['total_cost'],
                estimated_profit=prof['estimated_profit'],
                profit_margin=prof['profit_margin'],
                roi=prof['roi'],
            )
            self.session.add(match)
            matches.append(match)

            src = cost_data['source']
            logger.info(f"  ✓ Linked: {supplier.name[:50]}")
            logger.info(f"    Cost=£{cost_data['total_cost']} ({src}) | "
                        f"Profit=£{prof['estimated_profit']} | Margin={prof['profit_margin']:.0%}")

            if prof['profit_margin'] > best_margin:
                best_margin = prof['profit_margin']
                best_match = match

        # Auto-select preferred supplier (highest margin)
        if best_match and best_margin > 0:
            best_match.is_preferred = True
            logger.info(f"  ★ Preferred supplier: margin={best_margin:.0%}")

        self.session.commit()
        return matches

    def _get_demo_suppliers(self) -> Dict[str, Any]:
        """Fallback suppliers when Google API is unavailable."""
        logger.warning("Google API not configured — using fallback supplier platforms.")
        logger.warning("Configure GOOGLE_API_KEY and GOOGLE_SEARCH_ENGINE_ID in .env for real supplier discovery.")
        logger.info("Using category-based cost estimation for profitability calculations.")
        return {
            'all_suppliers': [
                {
                    'platform': 'Alibaba',
                    'name': 'Alibaba Wholesale Marketplace',
                    'url': 'https://www.alibaba.com',
                    'supplier_type': 'wholesaler',
                    'price_data': None,
                    'description': 'B2B wholesale marketplace. Costs auto-estimated from category ratios.'
                },
                {
                    'platform': 'Global Sources',
                    'name': 'Global Sources Trade Platform',
                    'url': 'https://www.globalsources.com',
                    'supplier_type': 'wholesaler',
                    'price_data': None,
                    'description': 'B2B trade platform. Costs auto-estimated from category ratios.'
                }
            ]
        }

    def backfill_zero_cost_links(self) -> int:
        """
        Backfill cost estimates for existing product-supplier links with zero costs.

        This handles products from previous runs where costs weren't estimated.

        Returns:
            Number of links updated
        """
        zero_cost_links = self.session.query(ProductSupplier, Product).join(
            Product, ProductSupplier.asin == Product.asin
        ).filter(
            ProductSupplier.supplier_cost <= 0,
            Product.current_price > 0,
        ).all()

        if not zero_cost_links:
            return 0

        updated = 0
        for ps, product in zero_cost_links:
            # Get supplier info for platform detection
            supplier = self.session.query(Supplier).filter(
                Supplier.supplier_id == ps.supplier_id
            ).first()

            platform = ''
            if supplier and supplier.notes:
                if 'Alibaba' in supplier.name:
                    platform = 'alibaba'
                elif 'Global Sources' in supplier.name:
                    platform = 'global sources'

            info = {'platform': platform, 'price_data': None}
            cost_data = self._estimate_supplier_cost(product, info)

            if cost_data['total_cost'] > 0:
                amazon_price = float(product.current_price or 0)
                prof = self._calculate_profitability(
                    amazon_price, cost_data['total_cost'], product.category or '')

                ps.supplier_cost = cost_data['supplier_cost']
                ps.shipping_cost = cost_data['shipping_cost']
                ps.total_cost = cost_data['total_cost']
                ps.estimated_profit = prof['estimated_profit']
                ps.profit_margin = prof['profit_margin']
                ps.roi = prof['roi']
                updated += 1

        self.session.commit()
        if updated:
            logger.info(f"  ↻ Backfilled cost estimates for {updated} existing supplier links")
        return updated

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

        # First, backfill any existing zero-cost links from previous runs
        backfilled = self.backfill_zero_cost_links()
        if backfilled:
            logger.info(f"Backfilled {backfilled} existing links with cost estimates")

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
            suppliers, supplier_infos = self.create_suppliers_from_google(discovery_result)

            # Match product to suppliers with auto-estimated costs
            matches = self.match_product_to_suppliers(product, suppliers, supplier_infos)

            if matches:
                total_matches += len(matches)
                products_matched += 1
                costed = sum(1 for m in matches if m.supplier_cost and m.supplier_cost > 0)
                logger.info(f"✓ Linked {len(matches)} suppliers ({costed} with cost estimates)")

        # Count products with real costs now
        costed_products = self.session.query(ProductSupplier).filter(
            ProductSupplier.supplier_cost > 0
        ).distinct(ProductSupplier.asin).count()

        logger.info(f"\n{'='*60}")
        logger.info("PHASE 3 COMPLETE - Automated Supplier Discovery & Costing")
        logger.info(f"{'='*60}")
        logger.info(f"Products processed: {products_matched}")
        logger.info(f"Supplier links created: {total_matches}")
        logger.info(f"Products with cost estimates: {costed_products}")
        logger.info(f"")
        logger.info(f"Costs are auto-estimated from:")
        logger.info(f"  1. Prices extracted from supplier listings")
        logger.info(f"  2. Category-based wholesale ratios")
        logger.info(f"  → Phase 4 & 5 will use these for repricing & forecasting")
        logger.info(f"  → Refine costs: uv run python tools/manage_suppliers.py update <asin>")
        logger.info(f"{'='*60}")

        return {
            'products_matched': products_matched,
            'total_matches': total_matches,
            'costed_products': costed_products,
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
