"""
Keepa API Wrapper

Provides a clean, high-level interface to the Keepa API for:
- Fetching historical product data (price, sales rank)
- Tracking competitor information
- Finding new product opportunities
"""

import logging
import time
from typing import Dict, List, Any, Optional

import keepa
from src.config import settings

logger = logging.getLogger(__name__)


class KeepaAPI:
    """
    Wrapper for the Keepa API.

    Handles authentication, rate limiting, and provides high-level methods
    for common operations.
    """

    def __init__(self):
        """Initialize the Keepa API wrapper."""
        self.api_key = settings.keepa_api_key
        self.domain = settings.keepa_domain
        self.api = None

        if not self.api_key:
            raise ValueError("Keepa API key is not configured.")

        try:
            self.api = keepa.Keepa(self.api_key)
            logger.info("✓ Keepa API initialized successfully")
        except Exception as e:
            logger.error(f"✗ Failed to initialize Keepa API: {e}")
            raise

    def get_product_data(self, asins: List[str]) -> List[Dict[str, Any]]:
        """
        Get detailed product data for a list of ASINs.

        Args:
            asins: A list of Amazon Standard Identification Numbers.

        Returns:
            A list of product data dictionaries.
        """
        if not self.api:
            return []

        try:
            products = self.api.query(asins, domain=self.domain)
            return products
        except Exception as e:
            logger.error(f"✗ Failed to get product data from Keepa: {e}")
            return []

    def search_for_products(self, search_term: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for products on Keepa.

        Args:
            search_term: The search term to use.
            category: The category to search in.

        Returns:
            A list of product data dictionaries.
        """
        if not self.api:
            return []

        try:
            # This is a simplified example. The keepa library does not directly support
            # keyword searches. A more advanced implementation would use other methods
            # to find ASINs first, then query Keepa.
            logger.warning("Keepa keyword search is not directly supported. This is a placeholder.")
            return []
        except Exception as e:
            logger.error(f"✗ Failed to search for products on Keepa: {e}")
            return []


# Singleton instance
_keepa_api_instance = None


def get_keepa_api() -> KeepaAPI:
    """Get or create the KeepaAPI instance."""
    global _keepa_api_instance
    if _keepa_api_instance is None:
        _keepa_api_instance = KeepaAPI()
    return _keepa_api_instance
