"""
Phase 4: Dynamic Repricing Engine

Optimizes prices to maximize profitability while maintaining Buy Box ownership.
Uses real-time competitor monitoring and custom repricing rules.

Only processes products that have REAL supplier costs (cost > 0).
Supports dry-run mode to preview changes before applying.

Usage:
  uv run python -m src.phases.phase_4_repricing              # Dry-run (preview only)
  uv run python -m src.phases.phase_4_repricing --apply       # Apply price changes
  uv run python -m src.phases.phase_4_repricing --limit 10    # Process top 10 only
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Dict, Any, Optional
from decimal import Decimal

from src.database import SessionLocal, Product, ProductSupplier, Performance
from src.api_wrappers.keepa_api import get_keepa_api
from src.api_wrappers.amazon_sp_api import get_sp_api
from src.config import settings, AMAZON_REFERRAL_FEES, AMAZON_FBA_FEE_DEFAULT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class RepricingEngine:
    """
    Dynamic repricing engine with custom rules.

    Features:
    - Only processes products with real supplier costs
    - Real-time competitor price monitoring via Keepa
    - Algorithmic repricing with margin protection
    - Buy Box optimization
    - Price bounds enforcement
    - Dry-run mode for previewing changes
    """

    def __init__(self, dry_run: bool = True):
        """
        Initialize the repricing engine.

        Args:
            dry_run: If True, preview changes without applying them
        """
        self.session = SessionLocal()
        self.keepa = get_keepa_api()
        self.amazon_api = get_sp_api()
        self.dry_run = dry_run

        # Repricing configuration from settings
        self.target_buy_box_rate = settings.target_buy_box_win_rate
        self.min_profit_margin = settings.min_profit_margin
        self.price_adjustment_amount = float(settings.price_adjustment_amount)
        self.max_price_multiplier = settings.max_price_multiplier
        self.min_price_change_percent = settings.min_price_change_percent

        mode = "DRY-RUN" if dry_run else "LIVE"
        logger.info(f"Repricing engine initialized ({mode} mode)")

    def get_competitor_prices(self, asin: str) -> Dict[str, Any]:
        """
        Get current competitor prices from Keepa.

        Args:
            asin: Product ASIN

        Returns:
            Competitor price data
        """
        try:
            products = self.keepa.get_product_data([asin])

            if not products:
                logger.warning(f"  No Keepa data for {asin}")
                return {}

            product_data = products[0]
            data = product_data.get("data", {})

            import numpy as np

            def last_valid(arr):
                if arr is None or len(arr) == 0:
                    return None
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                return valid[-1] if valid else None

            competitor_data = {
                'amazon_price': last_valid(data.get("AMAZON", [])),
                'buy_box_price': last_valid(data.get("NEW", [])),
                'lowest_new': last_valid(data.get("NEW", [])),
                'num_sellers': int(last_valid(data.get("COUNT_NEW", [])) or 0),
            }

            prices = [p for p in [
                competitor_data['buy_box_price'],
                competitor_data['amazon_price'],
            ] if p is not None]

            if prices:
                competitor_data['lowest_new'] = min(prices)

            bb = competitor_data.get('buy_box_price') or 0
            low = competitor_data.get('lowest_new') or 0
            logger.info(f"  Competitor: Buy Box=£{bb:.2f}, Lowest=£{low:.2f}")

            return competitor_data

        except Exception as e:
            logger.error(f"  Error getting competitor prices for {asin}: {e}")
            return {}

    def calculate_price_bounds(self, product: Product,
                              product_supplier: ProductSupplier) -> Optional[Dict[str, Decimal]]:
        """
        Calculate minimum and maximum allowed prices.

        Requires real supplier costs (total_cost > 0).

        Formula:
        - Min Price = (Cost + Fees) / (1 - min_profit_margin)
        - Max Price = Cost * max_price_multiplier

        Returns:
            Dictionary with min_price, max_price, cost, fees — or None if costs invalid
        """
        total_cost = product_supplier.total_cost or Decimal("0")

        if total_cost <= 0:
            logger.warning(f"  No real costs for {product.asin} — skipping")
            return None

        price = Decimal(str(product.current_price or 0))
        if price <= 0:
            return None

        # Category-aware referral fee
        cat = (product.category or "").lower().strip()
        referral_rate = Decimal(str(
            AMAZON_REFERRAL_FEES.get(cat, AMAZON_REFERRAL_FEES["default"])
        ))
        referral_fee = price * referral_rate
        fba_fee = AMAZON_FBA_FEE_DEFAULT
        total_fees = referral_fee + fba_fee

        # Min price: ensures min_profit_margin after all costs
        # price - cost - fees >= margin * price
        # price * (1 - margin) >= cost + fees
        # price >= (cost + fees) / (1 - margin)
        min_price = (total_cost + total_fees) / Decimal(str(1 - self.min_profit_margin))
        min_price = min_price.quantize(Decimal('0.01'))

        # Max price: cap at cost * multiplier
        max_price = total_cost * Decimal(str(self.max_price_multiplier))
        max_price = max_price.quantize(Decimal('0.01'))

        # Ensure max >= min
        if max_price < min_price:
            max_price = (min_price * Decimal('1.2')).quantize(Decimal('0.01'))

        logger.info(f"  Bounds: Min=£{min_price}, Max=£{max_price} (cost=£{total_cost})")

        return {
            'min_price': min_price,
            'max_price': max_price,
            'cost': total_cost,
            'fees': total_fees
        }

    def apply_repricing_rules(self, current_price: Decimal,
                             competitor_price: Optional[float],
                             price_bounds: Dict[str, Decimal]) -> Decimal:
        """
        Apply custom repricing rules.

        Rules:
        1. No competitor data → conservative price (75% of min-max range)
        2. Competitor below min → stay at min (protect margin)
        3. Competitor above max → stay at max
        4. Competitor in range → undercut by £0.01
        """
        min_price = price_bounds['min_price']
        max_price = price_bounds['max_price']

        if competitor_price is None:
            new_price = min_price + (max_price - min_price) * Decimal('0.75')
            logger.info(f"  No competitor data → conservative: £{new_price:.2f}")
            return new_price.quantize(Decimal('0.01'))

        comp = Decimal(str(competitor_price))

        if comp < min_price:
            logger.info(f"  Competitor £{comp} < min £{min_price} → stay at min")
            return min_price

        if comp > max_price:
            logger.info(f"  Competitor £{comp} > max £{max_price} → stay at max")
            return max_price

        undercut = comp - Decimal(str(self.price_adjustment_amount))
        if undercut < min_price:
            undercut = min_price

        logger.info(f"  Undercut £{comp} → £{undercut}")
        return undercut.quantize(Decimal('0.01'))

    def update_amazon_price(self, asin: str, new_price: Decimal) -> bool:
        """
        Update product price on Amazon via SP-API.

        In dry-run mode, only logs the intended change.
        """
        if self.dry_run:
            logger.info(f"  [DRY-RUN] Would update {asin} to £{new_price:.2f}")
            return True

        try:
            result = self.amazon_api.update_price(
                sku=asin,
                price=float(new_price),
                currency='GBP'
            )

            if result:
                logger.info(f"  Updated Amazon price to £{new_price:.2f}")
                return True
            else:
                logger.warning(f"  Price update returned False")
                return False

        except Exception as e:
            logger.error(f"  Failed to update Amazon price: {e}")
            return False

    def process_product(self, product: Product,
                        product_supplier: ProductSupplier) -> Dict[str, Any]:
        """
        Process repricing for a single product.

        Args:
            product: Product to reprice
            product_supplier: Supplier link with real costs

        Returns:
            Repricing results
        """
        logger.info(f"\n{'-'*60}")
        logger.info(f"{product.asin} | £{product.current_price:.2f} | {(product.title or '')[:50]}")

        result = {
            'asin': product.asin,
            'title': (product.title or '')[:50],
            'old_price': float(product.current_price or 0),
            'new_price': None,
            'price_changed': False,
            'reason': ''
        }

        try:
            # 1. Calculate price bounds (requires real costs)
            price_bounds = self.calculate_price_bounds(product, product_supplier)
            if not price_bounds:
                result['reason'] = "Invalid costs"
                return result

            # 2. Get competitor prices from Keepa
            competitor_data = self.get_competitor_prices(product.asin)
            competitor_price = (
                competitor_data.get('lowest_new')
                or competitor_data.get('buy_box_price')
            )

            # 3. Apply repricing rules
            current_price = Decimal(str(product.current_price))
            new_price = self.apply_repricing_rules(
                current_price, competitor_price, price_bounds
            )
            result['new_price'] = float(new_price)

            # 4. Check if change is significant enough
            price_diff = abs(new_price - current_price)
            price_diff_pct = float(price_diff / current_price) if current_price > 0 else 0

            if price_diff_pct < self.min_price_change_percent:
                result['reason'] = f"Change too small ({price_diff_pct*100:.1f}%)"
                logger.info(f"  No change needed (diff {price_diff_pct*100:.1f}%)")
                return result

            # 5. Calculate profit at new price
            cost = price_bounds['cost']
            fees = price_bounds['fees']
            new_profit = new_price - cost - fees
            new_margin = float(new_profit / new_price) if new_price > 0 else 0

            logger.info(
                f"  £{current_price:.2f} → £{new_price:.2f} "
                f"({price_diff_pct*100:+.1f}%) | "
                f"profit=£{new_profit:.2f} margin={new_margin:.0%}"
            )

            # 6. Update price
            if self.update_amazon_price(product.asin, new_price):
                if not self.dry_run:
                    product.current_price = new_price
                    product.last_updated = datetime.utcnow()

                    # Record performance snapshot
                    perf = Performance(
                        asin=product.asin,
                        price=new_price,
                        competitor_price=Decimal(str(competitor_price)) if competitor_price else None,
                        net_profit=new_profit,
                        sales_rank=product.sales_rank,
                        data_source="repricing",
                    )
                    self.session.add(perf)

                result['price_changed'] = True
                result['reason'] = f"Repriced ({price_diff_pct*100:+.1f}%)"
            else:
                result['reason'] = "Amazon API update failed"

            return result

        except Exception as e:
            logger.error(f"  Error processing {product.asin}: {e}")
            result['reason'] = f"Error: {str(e)}"
            return result

    def run(self, limit: int = 50) -> Dict[str, Any]:
        """
        Run the repricing engine on products with real supplier costs.

        Args:
            limit: Maximum products to process

        Returns:
            Statistics
        """
        mode = "DRY-RUN" if self.dry_run else "LIVE"

        logger.info("=" * 60)
        logger.info(f"PHASE 4: DYNAMIC REPRICING ENGINE ({mode})")
        logger.info("=" * 60)
        logger.info(f"  Min Profit Margin:  {self.min_profit_margin*100:.0f}%")
        logger.info(f"  Price Adjustment:   £{self.price_adjustment_amount:.2f}")
        logger.info(f"  Max Multiplier:     {self.max_price_multiplier}x")
        logger.info(f"  Min Change:         {self.min_price_change_percent*100:.1f}%")

        # Only get products with REAL supplier costs (cost > 0)
        product_supplier_pairs = self.session.query(Product, ProductSupplier).join(
            ProductSupplier,
            Product.asin == ProductSupplier.asin
        ).filter(
            Product.status == 'active',
            ProductSupplier.supplier_cost > 0,
        ).order_by(
            Product.opportunity_score.desc()
        ).limit(limit).all()

        if not product_supplier_pairs:
            logger.info("\nNo products with real supplier costs found.")
            logger.info("Add costs first: uv run python tools/manage_suppliers.py status")
            return {
                'products_processed': 0, 'prices_updated': 0,
                'skipped': 0, 'errors': 0,
                'total_price_increase': 0.0, 'total_price_decrease': 0.0,
            }

        logger.info(f"\nFound {len(product_supplier_pairs)} products with real costs")

        stats = {
            'products_processed': 0,
            'prices_updated': 0,
            'total_price_increase': 0.0,
            'total_price_decrease': 0.0,
            'skipped': 0,
            'errors': 0,
        }

        results = []

        for product, product_supplier in product_supplier_pairs:
            # Rate limit Keepa calls
            if stats['products_processed'] > 0:
                time.sleep(1)

            result = self.process_product(product, product_supplier)
            stats['products_processed'] += 1
            results.append(result)

            if result['price_changed']:
                stats['prices_updated'] += 1
                diff = result['new_price'] - result['old_price']
                if diff > 0:
                    stats['total_price_increase'] += diff
                else:
                    stats['total_price_decrease'] += abs(diff)
            elif 'Error' in result.get('reason', ''):
                stats['errors'] += 1
            else:
                stats['skipped'] += 1

        if not self.dry_run:
            self.session.commit()

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"PHASE 4 COMPLETE ({mode})")
        logger.info(f"{'='*60}")
        logger.info(f"  Products processed: {stats['products_processed']}")
        logger.info(f"  Prices {'would change' if self.dry_run else 'updated'}: {stats['prices_updated']}")
        logger.info(f"  Skipped (no change): {stats['skipped']}")
        logger.info(f"  Errors: {stats['errors']}")

        if stats['prices_updated'] > 0:
            logger.info(f"  Total increase: £{stats['total_price_increase']:.2f}")
            logger.info(f"  Total decrease: £{stats['total_price_decrease']:.2f}")

        if self.dry_run and stats['prices_updated'] > 0:
            logger.info(f"\nTo apply these changes, re-run with --apply:")
            logger.info(f"  uv run python -m src.phases.phase_4_repricing --apply")

        # Print summary table
        if results:
            logger.info(f"\n{'ASIN':<12} {'Old':>7} {'New':>7} {'Diff':>7} {'Status'}")
            logger.info(f"{'-'*12} {'-'*7} {'-'*7} {'-'*7} {'-'*20}")
            for r in results:
                old = f"£{r['old_price']:.2f}"
                new = f"£{r['new_price']:.2f}" if r['new_price'] else "—"
                diff = f"£{r['new_price'] - r['old_price']:+.2f}" if r['new_price'] else "—"
                logger.info(f"  {r['asin']:<12} {old:>7} {new:>7} {diff:>7} {r['reason']}")

        logger.info(f"{'='*60}")
        return stats


def main():
    """Run Phase 4 repricing."""
    parser = argparse.ArgumentParser(description="Dynamic Repricing Engine")
    parser.add_argument("--apply", action="store_true",
                        help="Apply price changes (default: dry-run preview only)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max products to process (default: 50)")
    args = parser.parse_args()

    dry_run = not args.apply

    try:
        engine = RepricingEngine(dry_run=dry_run)
        stats = engine.run(limit=args.limit)

        logger.info(f"\nPhase 4 complete!")
        return True

    except Exception as e:
        logger.error(f"Phase 4 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
