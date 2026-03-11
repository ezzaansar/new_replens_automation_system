"""
Phase 2: Automated Product Discovery

Automatically finds products to analyze without manual ASIN input.
Uses Amazon Catalog API to search by keywords, then analyzes with Keepa.
"""

import logging
import sys
from typing import List, Set
from datetime import datetime

from src.phases.phase_2_discovery import ProductDiscoveryEngine
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


class AutoDiscoveryEngine:
    """
    Automatically discovers products to analyze.

    Methods:
    1. Keyword search - Search Amazon catalog by keywords
    2. Category browse - Browse specific categories
    3. Best sellers - Analyze best-selling products
    """

    def __init__(self):
        """Initialize auto-discovery engine."""
        self.sp_api = get_sp_api()
        self.discovery_engine = ProductDiscoveryEngine()

    def search_by_keywords(self, keywords: List[str], max_per_keyword: int = 20) -> Set[str]:
        """
        Search Amazon Catalog by keywords.

        Args:
            keywords: List of search terms
            max_per_keyword: Max ASINs to find per keyword

        Returns:
            Set of ASINs found
        """
        logger.info(f"Searching for products with {len(keywords)} keywords")
        all_asins = set()

        for keyword in keywords:
            logger.info(f"  Searching: '{keyword}'")

            try:
                results = self.sp_api.search_catalog(
                    keywords=keyword,
                    page_size=min(max_per_keyword, 20)
                )

                asins = results.get('asins', [])
                all_asins.update(asins)
                logger.info(f"    Found {len(asins)} products")

            except Exception as e:
                logger.error(f"    Error searching '{keyword}': {e}")
                continue

        logger.info(f"✓ Total unique ASINs found: {len(all_asins)}")
        return all_asins

    def search_by_categories(self, categories: List[str], max_per_category: int = 20) -> Set[str]:
        """
        Search by predefined category keywords.

        Args:
            categories: Category names (e.g., 'electronics', 'home')
            max_per_category: Max products per category

        Returns:
            Set of ASINs
        """
        # Category keyword mappings
        category_keywords = {
            'electronics': ['wireless earbuds', 'phone charger', 'bluetooth speaker', 'power bank'],
            'home': ['kitchen organizer', 'storage bins', 'cleaning supplies', 'home decor'],
            'beauty': ['skincare', 'makeup brush', 'hair care', 'beauty tools'],
            'sports': ['fitness tracker', 'yoga mat', 'resistance bands', 'water bottle'],
            'toys': ['educational toys', 'building blocks', 'puzzle games', 'stuffed animals'],
            'pet': ['dog toys', 'cat treats', 'pet grooming', 'pet accessories'],
            'office': ['desk organizer', 'notebook', 'pens', 'office supplies'],
            'automotive': ['car accessories', 'phone mount', 'car charger', 'cleaning tools'],
            'music': ['guitar strings', 'music accessories', 'instrument care', 'audio cables'],
            'health': ['vitamins', 'fitness supplement', 'health monitor', 'wellness products']
        }

        keywords = []
        for category in categories:
            cat_lower = category.lower()
            if cat_lower in category_keywords:
                keywords.extend(category_keywords[cat_lower])
                logger.info(f"Added keywords for category: {category}")
            else:
                logger.warning(f"Unknown category: {category}")

        if not keywords:
            logger.error("No valid categories provided")
            return set()

        return self.search_by_keywords(keywords, max_per_keyword=max_per_category)

    def discover_from_best_sellers(self, category: str = None, limit: int = 50) -> Set[str]:
        """
        Find ASINs from best sellers lists.

        Note: This is a placeholder - Amazon doesn't provide a direct
        best sellers API. You would need to:
        1. Use third-party tools (Keepa, Jungle Scout)
        2. Manually curate a list
        3. Scrape (not recommended)

        Args:
            category: Optional category filter
            limit: Max products to find

        Returns:
            Set of ASINs
        """
        logger.warning("Best sellers discovery not yet implemented")
        logger.info("Alternatives:")
        logger.info("  1. Use keyword search with popular terms")
        logger.info("  2. Manually add top ASINs to asin_list.txt")
        logger.info("  3. Use third-party tools like Jungle Scout")
        return set()

    def run_with_keywords(self, keywords: List[str], max_products: int = 50) -> dict:
        """
        Full discovery pipeline with keywords.

        Args:
            keywords: Search keywords
            max_products: Max products to analyze

        Returns:
            Discovery statistics
        """
        logger.info("="*80)
        logger.info("AUTOMATED PRODUCT DISCOVERY")
        logger.info("="*80)
        logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
        logger.info(f"Keywords: {', '.join(keywords)}")

        # Step 1: Find ASINs
        logger.info("\n[1/2] Finding products on Amazon...")
        asins = self.search_by_keywords(keywords, max_per_keyword=max_products // len(keywords))

        if not asins:
            logger.error("No products found! Try different keywords.")
            return {'asins_found': 0, 'opportunities': 0}

        # Limit to max_products
        asins_to_analyze = list(asins)[:max_products]
        logger.info(f"Will analyze {len(asins_to_analyze)} products")

        # Step 2: Analyze with Keepa
        logger.info("\n[2/2] Analyzing products with Keepa...")
        opportunities = self.discovery_engine.discover_products(asins_to_analyze)

        # Step 3: Save to database
        if opportunities:
            saved = self.discovery_engine.save_opportunities(opportunities)
            logger.info(f"\n✓ Saved {saved} opportunities to database")

        # Statistics
        logger.info("\n" + "="*80)
        logger.info("DISCOVERY COMPLETE")
        logger.info("="*80)
        logger.info(f"ASINs found: {len(asins)}")
        logger.info(f"ASINs analyzed: {len(asins_to_analyze)}")
        logger.info(f"Opportunities found: {len(opportunities)}")
        logger.info(f"High-score products (>60): {len([o for o in opportunities if o['opportunity_score'] >= 60])}")

        return {
            'asins_found': len(asins),
            'asins_analyzed': len(asins_to_analyze),
            'opportunities': len(opportunities)
        }

    def run_with_categories(self, categories: List[str], max_products: int = 50) -> dict:
        """
        Full discovery pipeline with categories.

        Args:
            categories: Category names
            max_products: Max products to analyze

        Returns:
            Discovery statistics
        """
        logger.info("="*80)
        logger.info("CATEGORY-BASED PRODUCT DISCOVERY")
        logger.info("="*80)
        logger.info(f"Categories: {', '.join(categories)}")

        # Find ASINs
        asins = self.search_by_categories(categories, max_per_category=max_products // len(categories))

        if not asins:
            logger.error("No products found!")
            return {'asins_found': 0, 'opportunities': 0}

        # Analyze
        asins_to_analyze = list(asins)[:max_products]
        opportunities = self.discovery_engine.discover_products(asins_to_analyze)

        # Save
        if opportunities:
            saved = self.discovery_engine.save_opportunities(opportunities)
            logger.info(f"\n✓ Saved {saved} opportunities")

        return {
            'asins_found': len(asins),
            'asins_analyzed': len(asins_to_analyze),
            'opportunities': len(opportunities)
        }


def main():
    """Run automated discovery."""
    import argparse

    parser = argparse.ArgumentParser(description='Automated Product Discovery')
    parser.add_argument('--keywords', nargs='+', help='Search keywords')
    parser.add_argument('--categories', nargs='+', help='Categories (electronics, home, beauty, etc.)')
    parser.add_argument('--max', type=int, default=50, help='Max products to analyze')

    args = parser.parse_args()

    engine = AutoDiscoveryEngine()

    if args.keywords:
        # Keyword search
        stats = engine.run_with_keywords(args.keywords, max_products=args.max)
    elif args.categories:
        # Category search
        stats = engine.run_with_categories(args.categories, max_products=args.max)
    else:
        # Default: multi-category discovery to validate across diverse products
        logger.info("No keywords/categories provided. Using default multi-category discovery")
        default_categories = ['electronics', 'home', 'beauty', 'music', 'health']
        stats = engine.run_with_categories(default_categories, max_products=args.max)

    # Summary
    if stats['opportunities'] > 0:
        logger.info("\n✓ Discovery successful!")
        logger.info("\nNext steps:")
        logger.info("1. View opportunities: uv run streamlit run src/dashboard/app_with_suppliers.py")
        logger.info("2. Match suppliers: uv run python -m src.phases.phase_3_sourcing_with_openai")
    else:
        logger.warning("\n⚠️  No opportunities found")
        logger.info("Try different keywords or categories")


if __name__ == "__main__":
    main()
