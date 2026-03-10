"""
Phase 2: Product Discovery Engine

Identifies high-potential replenishable products using:
1. Keepa API for historical data
2. Machine learning scoring model
3. Profitability analysis
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any
from decimal import Decimal
import numpy as np

from src.database import SessionLocal, Product, DatabaseOperations
from src.api_wrappers.keepa_api import get_keepa_api
from src.api_wrappers.amazon_sp_api import get_sp_api
from src.config import settings, SALES_RANK_THRESHOLDS, SELLER_COUNT_THRESHOLDS, PRICE_STABILITY_THRESHOLDS
from src.models.discovery_model import DiscoveryModel

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class ProductDiscoveryEngine:
    """
    Identifies high-potential replenishable products.

    Uses machine learning to score products based on:
    - Sales velocity
    - Competition level
    - Price stability
    - Profitability potential
    """

    def __init__(self):
        """Initialize the discovery engine."""
        self.keepa_api = get_keepa_api()
        self.sp_api = get_sp_api()
        self.db = DatabaseOperations()
        self.model = DiscoveryModel()
        self.session = SessionLocal()

    def extract_features(self, product_data: Dict[str, Any]) -> Dict[str, float]:
        """
        Extract features from Keepa product data for ML model.

        Args:
            product_data: Raw product data from Keepa API

        Returns:
            Dictionary of extracted features
        """
        try:
            asin = product_data.get("asin", "")
            title = product_data.get("title", "")

            # Extract category from categoryTree
            category_tree = product_data.get("categoryTree", [])
            category = category_tree[0]["name"] if category_tree else product_data.get("category", "")

            data = product_data.get("data", {})

            # --- Price ---
            # data['NEW'] and data['AMAZON'] are price arrays (already in currency units)
            new_data = data.get("NEW", [])
            amazon_data = data.get("AMAZON", [])
            listprice_data = data.get("LISTPRICE", [])

            def last_valid(arr):
                if arr is None or len(arr) == 0:
                    return None
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                return valid[-1] if valid else None

            def avg_valid(arr):
                if arr is None or len(arr) == 0:
                    return None
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                return sum(valid) / len(valid) if valid else None

            def std_valid(arr):
                if arr is None or len(arr) == 0:
                    return 0.0
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                if len(valid) < 2:
                    return 0.0
                return float(np.std(valid))

            avg_price = last_valid(new_data) or last_valid(amazon_data) or last_valid(listprice_data)
            if avg_price is None or avg_price <= 0:
                logger.warning(f"No valid price data for {asin}")
                return None

            # --- Price stability ---
            price_std = std_valid(new_data) or std_valid(amazon_data) or 0.0
            price_stability = 1 - min(1, price_std / avg_price) if avg_price > 0 else 0.5

            # --- Sales rank ---
            sales_data = data.get("SALES", [])
            avg_sales_rank = last_valid(sales_data) or 100000.0

            # --- Seller count ---
            count_new = data.get("COUNT_NEW", [])
            avg_seller_count = last_valid(count_new) or 10.0

            # --- Estimated monthly sales (rough estimate from sales rank) ---
            if avg_sales_rank > 0:
                estimated_monthly_sales = max(1, int(100000 / avg_sales_rank))
            else:
                estimated_monthly_sales = 0

            features = {
                "asin": asin,
                "title": title,
                "category": category,
                "avg_price": float(avg_price),
                "price_std": float(price_std),
                "price_stability": float(price_stability),
                "avg_sales_rank": float(avg_sales_rank),
                "estimated_monthly_sales": estimated_monthly_sales,
                "avg_seller_count": float(avg_seller_count),
                "num_sellers_low": 1 if avg_seller_count < SELLER_COUNT_THRESHOLDS["low"] else 0,
                "sales_rank_good": 1 if avg_sales_rank < SALES_RANK_THRESHOLDS["good"] else 0,
                "price_stable": 1 if price_stability > 0.7 else 0,
            }

            return features

        except Exception as e:
            logger.error(f"✗ Error extracting features: {e}")
            return None

    def calculate_profitability(self, asin: str, price: Decimal) -> Dict[str, Any]:
        """
        Estimate profitability for a product.

        Args:
            asin: Product ASIN
            price: Current selling price

        Returns:
            Profitability metrics
        """
        try:
            # Get fee estimates from Amazon
            fees = self.sp_api.estimate_fees(asin, price)

            # Estimate cost of goods (this would come from supplier data in Phase 3)
            # For now, use a rough estimate of 40% of selling price
            estimated_cogs = price * Decimal("0.40")

            # Calculate profit
            total_fees = fees["referral_fee"] + fees["fba_fee"] + fees["variable_closing_fee"]
            net_profit = price - estimated_cogs - total_fees

            # Calculate margins
            profit_margin = (net_profit / price) if price > 0 else Decimal("0")
            roi = (net_profit / estimated_cogs) if estimated_cogs > 0 else Decimal("0")

            return {
                "estimated_cogs": float(estimated_cogs),
                "referral_fee": float(fees["referral_fee"]),
                "fba_fee": float(fees["fba_fee"]),
                "total_fees": float(total_fees),
                "net_profit": float(net_profit),
                "profit_margin": float(profit_margin),
                "roi": float(roi),
            }

        except Exception as e:
            logger.error(f"✗ Error calculating profitability for {asin}: {e}")
            return {
                "estimated_cogs": 0,
                "referral_fee": 0,
                "fba_fee": 0,
                "total_fees": 0,
                "net_profit": 0,
                "profit_margin": 0,
                "roi": 0,
            }

    def score_product(self, features: Dict[str, float], profitability: Dict[str, float]) -> float:
        """
        Score a product using the ML model.

        Args:
            features: Extracted features
            profitability: Profitability metrics

        Returns:
            Opportunity score (0-100)
        """
        try:
            # Combine features for ML model
            feature_vector = [
                features.get("price_stability", 0),
                features.get("num_sellers_low", 0),
                features.get("sales_rank_good", 0),
                features.get("estimated_monthly_sales", 0) / 100,  # Normalize
                profitability.get("profit_margin", 0),
                profitability.get("roi", 0) / 10,  # Normalize
            ]

            # Use ML model to score
            score = self.model.predict(feature_vector)

            # Apply business rules
            if profitability["profit_margin"] < settings.min_profit_margin:
                score *= 0.5  # Penalize low margin products

            if profitability["roi"] < settings.min_roi:
                score *= 0.5  # Penalize low ROI products

            if features["estimated_monthly_sales"] < settings.min_sales_velocity:
                score *= 0.5  # Penalize low velocity products

            return max(0, min(100, score * 100))  # Clamp to 0-100

        except Exception as e:
            logger.error(f"✗ Error scoring product: {e}")
            return 0

    def discover_products(self, asins: List[str]) -> List[Dict[str, Any]]:
        """
        Discover and score products.

        Args:
            asins: List of ASINs to analyze

        Returns:
            List of scored products
        """
        opportunities = []

        for asin in asins:
            try:
                logger.info(f"Analyzing {asin}...")

                # Get product data from Keepa
                product_data = self.keepa_api.get_product_data([asin])
                if not product_data:
                    continue

                product = product_data[0]

                # Extract features
                features = self.extract_features(product)
                if not features:
                    continue

                # Get current price
                current_price = Decimal(str(features.get("avg_price", 0)))

                # Calculate profitability
                profitability = self.calculate_profitability(asin, current_price)

                # Score the product
                score = self.score_product(features, profitability)

                # Create opportunity record
                opportunity = {
                    "asin": features["asin"],
                    "title": features["title"],
                    "category": features["category"],
                    "current_price": current_price,
                    "sales_rank": int(features["avg_sales_rank"]),
                    "estimated_monthly_sales": features["estimated_monthly_sales"],
                    "profit_potential": Decimal(str(profitability["net_profit"])),
                    "num_sellers": int(features["avg_seller_count"]),
                    "price_stability": features["price_stability"],
                    "opportunity_score": score,
                    "is_underserved": score >= 60,  # Threshold for underserved
                }

                opportunities.append(opportunity)

            except Exception as e:
                logger.error(f"✗ Error analyzing {asin}: {e}")
                continue

        # Sort by opportunity score
        opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)

        return opportunities

    def save_opportunities(self, opportunities: List[Dict[str, Any]]) -> int:
        """
        Save discovered opportunities to the database.

        Args:
            opportunities: List of opportunities

        Returns:
            Number of opportunities saved
        """
        saved = 0

        for opp in opportunities:
            try:
                # Check if product already exists
                existing = self.db.get_product(self.session, opp["asin"])

                if existing:
                    # Update existing product
                    existing.current_price = opp["current_price"]
                    existing.sales_rank = opp["sales_rank"]
                    existing.estimated_monthly_sales = opp["estimated_monthly_sales"]
                    existing.profit_potential = opp["profit_potential"]
                    existing.num_sellers = opp["num_sellers"]
                    existing.price_stability = opp["price_stability"]
                    existing.opportunity_score = opp["opportunity_score"]
                    existing.is_underserved = opp["is_underserved"]
                    existing.last_updated = datetime.utcnow()
                else:
                    # Create new product
                    new_product = Product(
                        asin=opp["asin"],
                        title=opp["title"],
                        category=opp["category"],
                        current_price=opp["current_price"],
                        sales_rank=opp["sales_rank"],
                        estimated_monthly_sales=opp["estimated_monthly_sales"],
                        profit_potential=opp["profit_potential"],
                        num_sellers=opp["num_sellers"],
                        price_stability=opp["price_stability"],
                        opportunity_score=opp["opportunity_score"],
                        is_underserved=opp["is_underserved"],
                        status="active",
                    )
                    self.session.add(new_product)

                self.session.commit()
                saved += 1

            except Exception as e:
                logger.error(f"✗ Error saving opportunity {opp.get('asin')}: {e}")
                self.session.rollback()

        return saved

    def run(self, asins: List[str] = None) -> int:
        """
        Run the product discovery engine.

        Args:
            asins: List of ASINs to analyze (if None, use predefined list)

        Returns:
            Number of opportunities found
        """
        logger.info("Starting Product Discovery Engine")
        logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")

        # If no ASINs provided, use a sample list
        if not asins:
            asins = [
                "B08C1K4LSV",  # Example ASIN
                "B08C1J9L3F",  # Example ASIN
            ]

        # Discover products
        opportunities = self.discover_products(asins)
        logger.info(f"Found {len(opportunities)} opportunities")

        # Save to database
        saved = self.save_opportunities(opportunities)
        logger.info(f"✓ Saved {saved} opportunities to database")

        # Print top opportunities
        if opportunities:
            logger.info("\nTop 5 Opportunities:")
            for i, opp in enumerate(opportunities[:5], 1):
                logger.info(f"  {i}. {opp['title']} (Score: {opp['opportunity_score']:.1f})")

        return len(opportunities)


def main():
    """Run Phase 2: Product Discovery."""
    try:
        engine = ProductDiscoveryEngine()
        count = engine.run()
        logger.info(f"✓ Phase 2 complete: {count} opportunities found")
        return True
    except Exception as e:
        logger.error(f"✗ Phase 2 failed: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
