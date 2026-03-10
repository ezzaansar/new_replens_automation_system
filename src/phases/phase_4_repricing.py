"""
Phase 4: Dynamic Repricing Engine

Optimizes prices to maximize profitability while maintaining Buy Box ownership.
Uses real-time competitor monitoring and custom repricing rules.
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal

from src.database import SessionLocal, Product, ProductSupplier, DatabaseOperations
from src.api_wrappers.keepa_api import get_keepa_api
from src.api_wrappers.amazon_sp_api import get_sp_api
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


class RepricingEngine:
    """
    Dynamic repricing engine with custom rules.

    Features:
    - Real-time competitor price monitoring
    - Algorithmic repricing with margin protection
    - Buy Box optimization
    - Price bounds enforcement
    """

    def __init__(self):
        """Initialize the repricing engine."""
        self.session = SessionLocal()
        self.db = DatabaseOperations()
        self.keepa = get_keepa_api()
        self.amazon_api = get_sp_api()

        # Repricing configuration from settings
        self.target_buy_box_rate = settings.target_buy_box_win_rate
        self.min_profit_margin = settings.min_profit_margin
        self.price_adjustment_amount = float(settings.price_adjustment_amount)
        self.max_price_multiplier = settings.max_price_multiplier
        self.min_price_change_percent = settings.min_price_change_percent

        logger.info("✓ Repricing engine initialized")

    def get_competitor_prices(self, asin: str) -> Dict[str, Any]:
        """
        Get current competitor prices from Keepa.

        Args:
            asin: Product ASIN

        Returns:
            Competitor price data
        """
        try:
            # Get fresh Keepa data
            products = self.keepa.get_product_data([asin])

            if not products:
                logger.warning(f"No Keepa data for {asin}")
                return {}

            product_data = products[0]
            data = product_data.get("data", {})

            import numpy as np

            def last_valid(arr):
                if arr is None or len(arr) == 0:
                    return None
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                return valid[-1] if valid else None

            # Extract key prices from data arrays
            competitor_data = {
                'amazon_price': last_valid(data.get("AMAZON", [])),
                'buy_box_price': last_valid(data.get("NEW", [])),
                'lowest_new': last_valid(data.get("NEW", [])),
                'lowest_fba': None,
                'num_sellers': int(last_valid(data.get("COUNT_NEW", [])) or 0),
            }

            # Use lowest available as competitor price
            prices = [p for p in [
                competitor_data['buy_box_price'],
                competitor_data['amazon_price'],
            ] if p is not None]

            if prices:
                competitor_data['lowest_new'] = min(prices)

            logger.info(f"  Competitor prices for {asin}: Buy Box=£{competitor_data.get('buy_box_price', 0):.2f}, "
                       f"Lowest=£{competitor_data.get('lowest_new', 0):.2f}")

            return competitor_data

        except Exception as e:
            logger.error(f"✗ Error getting competitor prices for {asin}: {e}")
            return {}

    def calculate_price_bounds(self, product: Product,
                              product_supplier: ProductSupplier) -> Dict[str, Decimal]:
        """
        Calculate minimum and maximum allowed prices.

        Formula:
        - Min Price = Cost + Fees + Target Margin
        - Max Price = Cost × Max Multiplier

        Args:
            product: Product to price
            product_supplier: Best supplier match

        Returns:
            Dictionary with min_price and max_price
        """
        try:
            # Get costs
            total_cost = product_supplier.total_cost
            amazon_price = Decimal(str(product.current_price))

            # Calculate Amazon fees (15% referral + £3 FBA estimate)
            amazon_fees = Decimal(str(round(float(amazon_price) * 0.15 + 3.00, 2)))

            # Min price = Cost + Fees + Target margin
            # We want profit to be at least min_profit_margin × selling price
            # So: selling_price - cost - fees >= min_profit_margin × selling_price
            # Rearranging: selling_price × (1 - min_profit_margin) >= cost + fees
            # selling_price >= (cost + fees) / (1 - min_profit_margin)

            min_price = (total_cost + amazon_fees) / Decimal(str(1 - self.min_profit_margin))
            min_price = Decimal(str(round(float(min_price), 2)))

            # Max price = Cost × Max Multiplier
            max_price = total_cost * Decimal(str(self.max_price_multiplier))
            max_price = Decimal(str(round(float(max_price), 2)))

            # Ensure max >= min
            if max_price < min_price:
                max_price = min_price * Decimal('1.2')  # Add 20% buffer

            logger.info(f"  Price bounds: Min=£{min_price:.2f}, Max=£{max_price:.2f}")

            return {
                'min_price': min_price,
                'max_price': max_price,
                'cost': total_cost,
                'fees': amazon_fees
            }

        except Exception as e:
            logger.error(f"✗ Error calculating price bounds: {e}")
            # Safe defaults
            return {
                'min_price': Decimal('10.00'),
                'max_price': Decimal('50.00'),
                'cost': Decimal('0'),
                'fees': Decimal('0')
            }

    def apply_repricing_rules(self, current_price: Decimal,
                             competitor_price: Optional[float],
                             price_bounds: Dict[str, Decimal]) -> Decimal:
        """
        Apply custom repricing rules.

        Rules:
        1. If competitor price is within bounds, undercut by £0.01
        2. If competitor price < min, stay at min
        3. If competitor price > max, stay at max
        4. If no competitor data, use midpoint of bounds

        Args:
            current_price: Current listing price
            competitor_price: Competitor's price (can be None)
            price_bounds: Min/max price constraints

        Returns:
            New optimal price
        """
        min_price = price_bounds['min_price']
        max_price = price_bounds['max_price']

        # Rule 1: No competitor data - use conservative pricing
        if competitor_price is None:
            # Start at 75% of the way from min to max
            new_price = min_price + (max_price - min_price) * Decimal('0.75')
            logger.info(f"  No competitor data, using conservative price: £{new_price:.2f}")
            return Decimal(str(round(float(new_price), 2)))

        competitor_price_decimal = Decimal(str(competitor_price))

        # Rule 2: Competitor below minimum - stay at minimum
        if competitor_price_decimal < min_price:
            logger.info(f"  Competitor (£{competitor_price:.2f}) below min, staying at min: £{min_price:.2f}")
            return min_price

        # Rule 3: Competitor above maximum - stay at maximum
        if competitor_price_decimal > max_price:
            logger.info(f"  Competitor (£{competitor_price:.2f}) above max, staying at max: £{max_price:.2f}")
            return max_price

        # Rule 4: Competitor within bounds - undercut by adjustment amount
        undercut_price = competitor_price_decimal - Decimal(str(self.price_adjustment_amount))

        # Ensure we don't go below minimum
        if undercut_price < min_price:
            undercut_price = min_price

        logger.info(f"  Undercutting competitor (£{competitor_price:.2f}) → £{undercut_price:.2f}")
        return Decimal(str(round(float(undercut_price), 2)))

    def update_amazon_price(self, asin: str, new_price: Decimal) -> bool:
        """
        Update product price on Amazon via SP-API.

        Args:
            asin: Product ASIN
            new_price: New price to set

        Returns:
            True if successful
        """
        try:
            result = self.amazon_api.update_price(
                sku=asin,  # Assuming SKU = ASIN for simplicity
                price=float(new_price),
                currency='GBP'
            )

            if result:
                logger.info(f"  ✓ Updated Amazon price to £{new_price:.2f}")
                return True
            else:
                logger.warning(f"  ⚠ Price update returned False")
                return False

        except Exception as e:
            logger.error(f"  ✗ Failed to update Amazon price: {e}")
            return False

    def process_product(self, product: Product) -> Dict[str, Any]:
        """
        Process repricing for a single product.

        Args:
            product: Product to reprice

        Returns:
            Repricing results
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {product.title}")
        logger.info(f"ASIN: {product.asin}")
        logger.info(f"Current Price: £{product.current_price:.2f}")

        result = {
            'asin': product.asin,
            'old_price': float(product.current_price),
            'new_price': None,
            'price_changed': False,
            'reason': ''
        }

        try:
            # 1. Get best supplier match
            best_match = self.session.query(ProductSupplier).filter(
                ProductSupplier.asin == product.asin,
                ProductSupplier.is_preferred == True
            ).first()

            if not best_match:
                # Get any match
                best_match = self.session.query(ProductSupplier).filter(
                    ProductSupplier.asin == product.asin
                ).order_by(ProductSupplier.roi.desc()).first()

            if not best_match:
                result['reason'] = "No supplier match found"
                logger.warning("  ⚠ No supplier match - skipping")
                return result

            # 2. Calculate price bounds
            price_bounds = self.calculate_price_bounds(product, best_match)

            # 3. Get competitor prices
            competitor_data = self.get_competitor_prices(product.asin)
            competitor_price = competitor_data.get('lowest_new') or competitor_data.get('buy_box_price')

            # 4. Apply repricing rules
            current_price = Decimal(str(product.current_price))
            new_price = self.apply_repricing_rules(
                current_price,
                competitor_price,
                price_bounds
            )

            result['new_price'] = float(new_price)

            # 5. Check if price change is significant
            price_diff = abs(new_price - current_price)
            price_diff_pct = float(price_diff / current_price) if current_price > 0 else 0

            if price_diff_pct < self.min_price_change_percent:
                result['reason'] = f"Price change too small ({price_diff_pct*100:.1f}%)"
                logger.info(f"  → No change needed (diff: {price_diff_pct*100:.1f}%)")
                return result

            # 6. Update Amazon price
            logger.info(f"  → Price change: £{current_price:.2f} → £{new_price:.2f} ({price_diff_pct*100:.1f}%)")

            if self.update_amazon_price(product.asin, new_price):
                # Update database
                product.current_price = new_price
                self.session.commit()

                result['price_changed'] = True
                result['reason'] = f"Repriced ({price_diff_pct*100:.1f}% change)"
                logger.info(f"  ✓ Repricing complete")
            else:
                result['reason'] = "Amazon API update failed"

            return result

        except Exception as e:
            logger.error(f"✗ Error processing {product.asin}: {e}")
            result['reason'] = f"Error: {str(e)}"
            return result

    def run(self, limit: int = 50) -> Dict[str, Any]:
        """
        Run the repricing engine on active products.

        Args:
            limit: Maximum products to process

        Returns:
            Statistics
        """
        logger.info("="*60)
        logger.info("PHASE 4: DYNAMIC REPRICING ENGINE")
        logger.info("="*60)
        logger.info(f"Configuration:")
        logger.info(f"  Target Buy Box Rate: {self.target_buy_box_rate*100:.0f}%")
        logger.info(f"  Min Profit Margin: {self.min_profit_margin*100:.0f}%")
        logger.info(f"  Price Adjustment: £{self.price_adjustment_amount:.2f}")
        logger.info(f"  Max Price Multiplier: {self.max_price_multiplier}x")

        # Get products with supplier matches
        products = self.session.query(Product).join(
            ProductSupplier,
            Product.asin == ProductSupplier.asin
        ).filter(
            Product.status == 'active'
        ).limit(limit).all()

        logger.info(f"\nFound {len(products)} products to process")

        stats = {
            'products_processed': 0,
            'prices_updated': 0,
            'total_price_increase': 0.0,
            'total_price_decrease': 0.0,
            'skipped': 0,
            'errors': 0
        }

        for product in products:
            result = self.process_product(product)
            stats['products_processed'] += 1

            if result['price_changed']:
                stats['prices_updated'] += 1
                price_diff = result['new_price'] - result['old_price']
                if price_diff > 0:
                    stats['total_price_increase'] += price_diff
                else:
                    stats['total_price_decrease'] += abs(price_diff)
            elif 'Error' in result['reason']:
                stats['errors'] += 1
            else:
                stats['skipped'] += 1

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("PHASE 4 COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Products processed: {stats['products_processed']}")
        logger.info(f"Prices updated: {stats['prices_updated']}")
        logger.info(f"Skipped: {stats['skipped']}")
        logger.info(f"Errors: {stats['errors']}")
        if stats['prices_updated'] > 0:
            logger.info(f"Total increased: £{stats['total_price_increase']:.2f}")
            logger.info(f"Total decreased: £{stats['total_price_decrease']:.2f}")
        logger.info(f"{'='*60}")

        return stats


def main():
    """Run Phase 4 repricing."""
    try:
        engine = RepricingEngine()
        stats = engine.run()

        logger.info(f"\n✓ Phase 4 complete!")
        return True

    except Exception as e:
        logger.error(f"✗ Phase 4 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
