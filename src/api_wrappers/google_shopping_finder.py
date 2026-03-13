"""
Google Shopping Supplier Finder

Uses Google Custom Search API to find suppliers for products.
Searches across UK wholesalers, B2B platforms, and retail arbitrage sources
via a Google Programmable Search Engine configured with approved supplier sites.
"""

import json
import logging
import os
import requests
import re
import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus, urlparse

from src.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# UK WHOLESALER & SUPPLIER SITE REGISTRY
# ============================================================================

# All sites configured in the Google Programmable Search Engine (cx)
# Organised by category for platform detection

UK_FMCG_WHOLESALERS = {
    'dcsgroup.com': 'DCS Group',
    'costco.co.uk': 'Costco UK',
    'booker.co.uk': 'Booker Wholesale',
    'bestwaywholesale.co.uk': 'Bestway Wholesale',
    'dhamecha.com': 'Dhamecha Cash & Carry',
    'hancocks.co.uk': 'Hancocks',
}

UK_GENERAL_WHOLESALERS = {
    'harrisonsdirect.co.uk': 'Harrisons Direct',
    'poundwholesale.co.uk': 'Pound Wholesale',
    'dkwholesale.com': 'DK Wholesale',
    'mxwholesale.co.uk': 'MX Wholesale',
    'gemimports.co.uk': 'Gem Imports',
    'clearance-king.co.uk': 'Clearance King',
    'petbrands.com': 'PetBrands',
}

UK_WHOLESALE_DIRECTORIES = {
    'esources.co.uk': 'eSources',
    'thewholesaler.co.uk': 'The Wholesaler',
    'wholesale-deals.co.uk': 'Wholesale Deals',
}

UK_RETAIL_ARBITRAGE = {
    'boots.com': 'Boots',
    'superdrug.com': 'Superdrug',
    'argos.co.uk': 'Argos',
    'smythstoys.com': 'Smyths Toys',
    'homebargains.co.uk': 'Home Bargains',
    'bmstores.co.uk': 'B&M Stores',
}

B2B_MANUFACTURER_PLATFORMS = {
    'alibaba.com': 'Alibaba',
    'globalsources.com': 'Global Sources',
    'made-in-china.com': 'Made-in-China',
    'dhgate.com': 'DHgate',
    'tradekey.com': 'TradeKey',
    'indiamart.com': 'IndiaMart',
}

# Combined lookup: domain → (platform_name, supplier_type)
KNOWN_SUPPLIER_SITES: Dict[str, tuple] = {}
for domain, name in UK_FMCG_WHOLESALERS.items():
    KNOWN_SUPPLIER_SITES[domain] = (name, 'uk_wholesaler')
for domain, name in UK_GENERAL_WHOLESALERS.items():
    KNOWN_SUPPLIER_SITES[domain] = (name, 'uk_wholesaler')
for domain, name in UK_WHOLESALE_DIRECTORIES.items():
    KNOWN_SUPPLIER_SITES[domain] = (name, 'uk_directory')
for domain, name in UK_RETAIL_ARBITRAGE.items():
    KNOWN_SUPPLIER_SITES[domain] = (name, 'uk_retail')
for domain, name in B2B_MANUFACTURER_PLATFORMS.items():
    KNOWN_SUPPLIER_SITES[domain] = (name, 'manufacturer')


class RateLimiter:
    """Thread-safe rate limiter for API calls."""

    def __init__(self, max_calls_per_second: float = 1.0, max_calls_per_day: int = 100):
        self.min_interval = 1.0 / max_calls_per_second
        self.max_daily = max_calls_per_day
        self._lock = threading.Lock()
        self._last_call_time = 0.0

    def wait(self):
        """Block until it's safe to make the next call."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                logger.debug(f"Rate limiter: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            self._last_call_time = time.monotonic()


class GoogleShoppingFinder:
    """
    Uses Google Custom Search API to find suppliers.

    Searches across a Google Programmable Search Engine configured with:
    - UK FMCG wholesalers (DCS Group, Costco, Booker, Bestway, etc.)
    - UK general merchandise wholesalers (Harrisons, Pound Wholesale, etc.)
    - UK wholesale directories (eSources, The Wholesaler, etc.)
    - UK retail arbitrage sources (Boots, Superdrug, Argos, Smyths, etc.)
    - B2B manufacturer platforms (Alibaba, Global Sources, Made-in-China)
    """

    def __init__(self):
        """Initialize Google Shopping finder with rate limiting."""
        if not settings.google_api_key:
            raise ValueError("Google API key not configured in .env (GOOGLE_API_KEY)")

        if not settings.google_search_engine_id:
            raise ValueError("Google Search Engine ID not configured in .env (GOOGLE_SEARCH_ENGINE_ID)")

        self.api_key = settings.google_api_key
        self.cx = settings.google_search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"

        # Rate limiter: 1 request/second, 100/day (free tier)
        self._rate_limiter = RateLimiter(
            max_calls_per_second=1.0,
            max_calls_per_day=100,
        )

        logger.info("✓ Google Shopping finder initialized (with rate limiting)")

    # ========================================================================
    # QUOTA TRACKING
    # ========================================================================

    def _get_quota_file(self) -> str:
        """Path to quota tracking file."""
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'data', 'google_api_quota.json'
        )

    def _load_quota(self) -> Dict[str, Any]:
        """Load today's quota usage. Resets daily."""
        quota_file = self._get_quota_file()
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            with open(quota_file, 'r') as f:
                data = json.load(f)
            if data.get('date') != today:
                return {'date': today, 'queries_used': 0, 'limit': 100}
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {'date': today, 'queries_used': 0, 'limit': 100}

    def _save_quota(self, quota: Dict[str, Any]):
        """Save quota usage to file."""
        quota_file = self._get_quota_file()
        os.makedirs(os.path.dirname(quota_file), exist_ok=True)
        with open(quota_file, 'w') as f:
            json.dump(quota, f)

    def _check_quota(self) -> bool:
        """Check if we have quota remaining. Returns True if OK."""
        quota = self._load_quota()
        remaining = quota['limit'] - quota['queries_used']
        if remaining <= 0:
            logger.warning(f"Google API daily quota exhausted ({quota['queries_used']}/{quota['limit']})")
            return False
        if remaining <= 10:
            logger.warning(f"Google API quota low: {remaining} queries remaining today")
        return True

    def _record_query(self):
        """Record a query against today's quota."""
        quota = self._load_quota()
        quota['queries_used'] += 1
        self._save_quota(quota)
        logger.debug(f"Google API quota: {quota['queries_used']}/{quota['limit']}")

    # ========================================================================
    # BRAND DETECTION
    # ========================================================================

    def _is_likely_brand_name(self, word: str) -> bool:
        """
        Check if a word at the start of a product title is likely a brand name.

        Uses heuristics to distinguish brand names (Morpilot, SAMSUNG, JBL)
        from product descriptors (Portable, Wireless, Pet).
        """
        if len(word) <= 2:
            return False

        word_lower = word.lower()

        # Common English words that start product descriptions - NOT brands
        common_product_words = {
            # Product categories & descriptors
            'pet', 'dog', 'cat', 'baby', 'kids', 'car', 'home', 'garden',
            'kitchen', 'outdoor', 'indoor', 'mini', 'large', 'small', 'big',
            'portable', 'wireless', 'electric', 'digital', 'automatic', 'manual',
            'heavy', 'light', 'multi', 'purpose', 'adjustable', 'foldable',
            'collapsible', 'removable', 'reusable', 'waterproof', 'rechargeable',
            'solar', 'magnetic', 'thermal', 'insulated', 'durable', 'lightweight',
            # Materials
            'stainless', 'steel', 'plastic', 'wooden', 'metal', 'glass',
            'silicone', 'leather', 'cotton', 'nylon', 'rubber', 'bamboo',
            'ceramic', 'aluminium', 'aluminum', 'copper', 'iron', 'foam',
            # Colors
            'black', 'white', 'red', 'blue', 'green', 'pink', 'grey', 'gray',
            'purple', 'yellow', 'orange', 'brown', 'gold', 'silver', 'clear',
            # Sizes/quantities
            'double', 'single', 'triple', 'dual', 'pack', 'set', 'pair',
            'extra', 'super', 'ultra', 'mega', 'jumbo',
            # Locations/rooms
            'wall', 'desk', 'floor', 'table', 'shelf', 'door', 'window',
            'bathroom', 'bedroom', 'living', 'room', 'office', 'garage',
            # Body/nature
            'water', 'food', 'air', 'hair', 'skin', 'body', 'hand', 'foot',
            'face', 'eye', 'ear', 'nose', 'nail', 'teeth', 'tooth',
            # Activities
            'travel', 'sport', 'fitness', 'yoga', 'camping', 'running',
            'swimming', 'hiking', 'fishing', 'cycling', 'cooking',
            # Quality/marketing
            'universal', 'professional', 'premium', 'deluxe',
            'pro', 'max', 'plus', 'lite', 'original',
            'new', 'upgraded', 'improved', 'classic', 'modern', 'luxury',
            # Common product nouns
            'carrier', 'bag', 'case', 'box', 'holder', 'stand', 'rack',
            'organizer', 'storage', 'container', 'basket', 'tray', 'bin',
            'lamp', 'light', 'bulb', 'fan', 'heater', 'cooler',
            'brush', 'comb', 'mirror', 'towel', 'mat', 'pad',
            'cable', 'charger', 'adapter', 'plug', 'socket', 'switch',
            'toy', 'game', 'puzzle', 'ball', 'doll', 'bear',
            'cup', 'mug', 'bottle', 'flask', 'jug', 'bowl', 'plate',
            'pen', 'pencil', 'marker', 'notebook', 'paper',
            'tool', 'drill', 'saw', 'hammer', 'wrench',
            'glove', 'mask', 'hat', 'cap', 'scarf', 'sock',
            'cream', 'gel', 'spray', 'oil', 'soap', 'shampoo', 'lotion',
            'clip', 'hook', 'ring', 'chain', 'rope', 'wire', 'tape',
            'cover', 'protector', 'guard', 'shield', 'wrap',
            'cleaner', 'remover', 'filler', 'sealer', 'cutter',
            'bed', 'pillow', 'blanket', 'sheet', 'mattress', 'cushion',
            'wheel', 'tire', 'seat', 'belt', 'strap',
            'dispenser', 'feeder', 'filter', 'pump', 'valve', 'hose',
            'safe', 'lock', 'key', 'alarm', 'sensor', 'camera',
            'speaker', 'headphone', 'earphone', 'microphone',
            'screen', 'display', 'monitor', 'keyboard', 'mouse',
            # Common all-caps product terms (not brands)
            'led', 'usb', 'lcd', 'uv', 'hdmi', 'pvc', 'abs', 'diy',
            # Common adjectives/verbs at title start
            'anti', 'non', 'self', 'all', 'full', 'half',
            'long', 'short', 'wide', 'narrow', 'thin', 'thick',
            'soft', 'hard', 'warm', 'cool', 'cold', 'hot',
            'natural', 'organic', 'eco', 'safe', 'free',
            'genuine', 'official', 'authentic', 'certified',
        }

        # If it's a common product word, NOT a brand
        if word_lower in common_product_words:
            return False

        # All caps and > 2 chars: likely brand (SAMSUNG, JBL, RENPHO)
        if word.isupper() and len(word) > 2:
            return True

        # Contains digits mixed with letters: likely model/brand (3M, V8)
        if re.search(r'[a-zA-Z]', word) and re.search(r'\d', word):
            return True

        # CamelCase within word: likely brand (iPhone, GoPro, EcoSmart)
        if len(word) > 2 and any(c.isupper() for c in word[1:]) and any(c.islower() for c in word):
            return True

        # Capitalized word that's not a common product term
        # Catches brands like "Morpilot", "Anker", "Joby", "Philips"
        if word[0].isupper() and len(word) >= 3 and word_lower not in common_product_words:
            return True

        return False

    def _simplify_product_title(self, title: str) -> str:
        """
        Simplify product title for better search results.

        Removes:
        - Brand names (all caps words at start)
        - Quantities (5 Pcs, Pack of 3, etc.)
        - Marketing fluff (High-End, Premium, Cute, Gifts, etc.)
        - Parenthetical info (Color names, model numbers)

        Args:
            title: Original product title

        Returns:
            Simplified title with key product terms only
        """
        simplified = title

        # Remove text in parentheses (often color names, model numbers)
        simplified = re.sub(r'\([^)]*\)', '', simplified)

        # Remove text in brackets
        simplified = re.sub(r'\[[^\]]*\]', '', simplified)

        # Remove common quantity phrases
        quantity_patterns = [
            r'\d+\s*pcs?\b',
            r'\d+\s*pack\b',
            r'pack\s*of\s*\d+',
            r'\d+\s*count\b',
            r'set\s*of\s*\d+',
        ]
        for pattern in quantity_patterns:
            simplified = re.sub(pattern, '', simplified, flags=re.IGNORECASE)

        # Remove marketing fluff words
        fluff_words = [
            'high-end', 'premium', 'professional', 'quality', 'best',
            'cute', 'beautiful', 'perfect', 'ideal', 'great',
            'gift', 'gifts', 'for women', 'for men', 'for kids',
            'series', 'collection', 'edition',
            'supplies', 'accessories',
        ]
        for fluff in fluff_words:
            simplified = re.sub(r'\b' + re.escape(fluff) + r'\b', '', simplified, flags=re.IGNORECASE)

        # Remove brand name(s) from start of title
        # Handles ALL-CAPS (SAMSUNG), CamelCase (GoPro), and proper nouns (Morpilot)
        words = simplified.split()
        brand_words_removed = []
        for i, word in enumerate(words[:3]):  # Check first 3 words max
            if self._is_likely_brand_name(word):
                brand_words_removed.append(word)
            else:
                break  # Stop at first non-brand word
        if brand_words_removed:
            words = words[len(brand_words_removed):]
            simplified = ' '.join(words)
            logger.debug(f"Stripped brand: '{' '.join(brand_words_removed)}'")

        # Clean up extra whitespace and commas
        simplified = re.sub(r'\s*,\s*', ' ', simplified)
        simplified = re.sub(r'\s+', ' ', simplified)
        simplified = simplified.strip()

        # Take first 5-8 key words (avoid too long queries)
        words = simplified.split()
        if len(words) > 8:
            # Try to keep size/spec words (numbers, mm, etc)
            key_words = []
            for word in words[:15]:
                if len(key_words) >= 8:
                    break
                # Keep if it has numbers or measurements
                if re.search(r'\d', word) or word.lower() in ['mm', 'cm', 'inch', 'oz', 'ml', 'l']:
                    key_words.append(word)
                # Or if it's a short descriptive word
                elif len(word) > 2 and len(key_words) < 5:
                    key_words.append(word)
            simplified = ' '.join(key_words) if key_words else ' '.join(words[:5])

        # If result is too short, keep more of original
        if len(simplified) < 10:
            words = title.split()[:5]
            simplified = ' '.join(words)

        logger.debug(f"Simplified title: '{title[:50]}...' → '{simplified}'")
        return simplified

    def _extract_product_keywords(self, title: str) -> List[str]:
        """
        Extract key product keywords for relevance matching.

        For "Earth Rated Pet Wipes for Dogs and Cats", returns:
        ['pet wipes', 'dog wipes', 'cat wipes', 'wipes', 'pet']

        Args:
            title: Product title

        Returns:
            List of keywords that search results must contain
        """
        # Remove brand name(s) from start using original case for detection
        original_words = title.split()
        brand_count = 0
        for i, word in enumerate(original_words[:3]):
            if self._is_likely_brand_name(word):
                brand_count += 1
            else:
                break
        # Work with lowercase words after brand removal
        words = [w.lower() for w in original_words[brand_count:]]

        # Find core product words (nouns that describe what the product IS)
        # These are the essential words that must appear in supplier results
        keywords = []

        # Extract 2-word product phrases (e.g., "pet wipes", "gel pens")
        for i in range(len(words) - 1):
            phrase = f"{words[i]} {words[i+1]}"
            # Skip generic phrases
            if not any(skip in phrase for skip in ['for dogs', 'for cats', 'for men', 'for women', 'and cats', 'and dogs']):
                if len(words[i]) > 2 and len(words[i+1]) > 2:
                    keywords.append(phrase)

        # Add single important product words
        important_product_words = []
        skip_words = {'for', 'and', 'with', 'the', 'of', 'in', 'on', 'to', 'a', 'an',
                      'dogs', 'cats', 'men', 'women', 'kids', 'children', 'adults',
                      'rated', 'brand', 'quality', 'premium', 'best', 'top', 'great'}

        for word in words:
            if len(word) > 3 and word not in skip_words:
                important_product_words.append(word)

        # Add the most important single words (first 2-3)
        keywords.extend(important_product_words[:3])

        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        logger.debug(f"Product keywords for '{title[:40]}...': {unique_keywords}")
        return unique_keywords[:5]  # Limit to 5 keywords

    def find_suppliers(self, product_title: str, max_results: int = 10) -> Dict[str, Any]:
        """
        Find suppliers for a product using Google Custom Search.

        Args:
            product_title: Product name/title
            max_results: Maximum number of results (default 10)

        Returns:
            Dictionary with supplier results
        """
        try:
            # Check quota before making request
            if not self._check_quota():
                return {'suppliers': [], 'error': 'quota_exhausted', 'quota_exceeded': True}

            # Simplify the product title for better search results
            simplified_title = self._simplify_product_title(product_title)

            # Extract keywords for relevance checking
            product_keywords = self._extract_product_keywords(product_title)

            # Search query — no site: restriction needed since the Programmable
            # Search Engine is already configured to only search approved UK
            # wholesaler, B2B, and retail arbitrage sites.
            query = f"{simplified_title} wholesale UK"

            logger.info(f"Simplified: '{product_title[:60]}...' → '{simplified_title}'")
            logger.info(f"Product keywords for matching: {product_keywords}")
            logger.info(f"Searching Google CSE for: {query}")

            # Rate limit before making request
            self._rate_limiter.wait()

            # Make API request
            params = {
                'key': self.api_key,
                'cx': self.cx,
                'q': query,
                'num': min(max_results, 10)  # Google limits to 10 per request
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            self._record_query()
            data = response.json()

            # Parse results with relevance checking
            suppliers = []
            search_items = data.get('items', [])

            logger.info(f"Google returned {len(search_items)} search results")

            rejected_count = 0
            for item in search_items:
                supplier = self._parse_search_result(item, product_keywords=product_keywords)
                if supplier:
                    suppliers.append(supplier)
                    logger.info(f"  ✓ Accepted: {supplier['platform']} - {supplier['name'][:50]}")
                else:
                    rejected_count += 1

            logger.info(f"✓ Found {len(suppliers)} relevant suppliers ({rejected_count} filtered out)")

            # No fallbacks that disable relevance checking - better to return 0 results
            # than irrelevant jute bags for dog pee pads

            return {
                'suppliers': suppliers,
                'total_results': data.get('searchInformation', {}).get('totalResults', 0),
                'search_query': query,
                'product_title': product_title,
                'keywords_used': product_keywords
            }

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.error(f"✗ RATE LIMITED: Google API quota exceeded (429)")
                logger.error(f"  Free tier: 100 queries/day. Wait until tomorrow or upgrade.")
                logger.error(f"  Upgrade at: https://developers.google.com/custom-search/v1/overview")
                return {'suppliers': [], 'error': 'rate_limited', 'quota_exceeded': True}
            else:
                logger.error(f"✗ Google API request failed: {e}")
                return {'suppliers': [], 'error': str(e)}
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ Google API request failed: {e}")
            return {'suppliers': [], 'error': str(e)}
        except Exception as e:
            logger.error(f"✗ Error finding suppliers: {e}")
            return {'suppliers': [], 'error': str(e)}

    def find_on_alibaba(self, product_title: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search specifically on Alibaba.

        Args:
            product_title: Product name
            max_results: Maximum results

        Returns:
            List of Alibaba supplier results
        """
        try:
            # Simplify title for better results
            simplified_title = self._simplify_product_title(product_title)
            product_keywords = self._extract_product_keywords(product_title)
            # Target Alibaba suppliers that ship to UK or have UK warehouse
            query = f"site:alibaba.com {simplified_title} ship to UK"

            logger.info(f"Alibaba search (UK shipping): '{simplified_title}' (from: '{product_title[:50]}...')")
            logger.info(f"Relevance keywords: {product_keywords}")

            self._rate_limiter.wait()

            params = {
                'key': self.api_key,
                'cx': self.cx,
                'q': query,
                'num': min(max_results, 10)
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            self._record_query()
            data = response.json()

            total_results_estimate = data.get('searchInformation', {}).get('totalResults', '0')
            items_returned = len(data.get('items', []))

            logger.info(f"Google returned {items_returned} items (estimated total: {total_results_estimate})")

            suppliers = []
            rejected = 0
            for item in data.get('items', []):
                supplier = self._parse_search_result(item, platform='Alibaba', product_keywords=product_keywords)
                if supplier:
                    suppliers.append(supplier)
                    logger.info(f"  ✓ {supplier['name'][:60]}")
                else:
                    rejected += 1

            logger.info(f"✓ Found {len(suppliers)} relevant Alibaba results ({rejected} filtered)")

            if items_returned == 0:
                logger.warning(f"⚠ Google found 0 results for: site:alibaba.com {simplified_title}")
                logger.warning(f"  This means your Google Custom Search Engine is not finding Alibaba")
                logger.warning(f"  Check: https://programmablesearchengine.google.com/")

            return suppliers

        except Exception as e:
            logger.error(f"✗ Alibaba search failed: {e}")
            return []

    def find_on_global_sources(self, product_title: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search specifically on Global Sources.

        Args:
            product_title: Product name
            max_results: Maximum results

        Returns:
            List of Global Sources supplier results
        """
        try:
            # Simplify title for better results
            simplified_title = self._simplify_product_title(product_title)
            product_keywords = self._extract_product_keywords(product_title)
            # Target Global Sources suppliers that ship to UK
            query = f"site:globalsources.com {simplified_title} UK"

            logger.info(f"Global Sources search (UK): '{simplified_title}' (from: '{product_title[:50]}...')")
            logger.info(f"Relevance keywords: {product_keywords}")

            self._rate_limiter.wait()

            params = {
                'key': self.api_key,
                'cx': self.cx,
                'q': query,
                'num': min(max_results, 10)
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            self._record_query()
            data = response.json()

            total_results_estimate = data.get('searchInformation', {}).get('totalResults', '0')
            items_returned = len(data.get('items', []))

            logger.info(f"Google returned {items_returned} items (estimated total: {total_results_estimate})")

            suppliers = []
            rejected = 0
            for item in data.get('items', []):
                supplier = self._parse_search_result(item, platform='Global Sources', product_keywords=product_keywords)
                if supplier:
                    suppliers.append(supplier)
                    logger.info(f"  ✓ {supplier['name'][:60]}")
                else:
                    rejected += 1

            logger.info(f"✓ Found {len(suppliers)} relevant Global Sources results ({rejected} filtered)")

            if items_returned == 0:
                logger.warning(f"⚠ Google found 0 results for: site:globalsources.com {simplified_title}")

            return suppliers

        except Exception as e:
            logger.error(f"✗ Global Sources search failed: {e}")
            return []

    def search_multiple_platforms(self, product_title: str) -> Dict[str, Any]:
        """
        Search across multiple B2B platforms.

        Args:
            product_title: Product name

        Returns:
            Dictionary with results from each platform
        """
        # Simplify title for better results
        simplified_title = self._simplify_product_title(product_title)

        logger.info(f"Searching multiple platforms for: {product_title[:60]}...")
        logger.info(f"Simplified: '{product_title[:60]}...' → '{simplified_title}'")

        # Use single general search to save API quota (instead of 2 separate searches)
        # This uses 1 API call instead of 2
        general_results = self.find_suppliers(product_title, max_results=10)

        # Check for quota exceeded
        if general_results.get('quota_exceeded'):
            return {'all_suppliers': [], 'quota_exceeded': True}

        # Categorize results by supplier type
        uk_wholesaler_results = []
        uk_retail_results = []
        manufacturer_results = []
        other_results = []

        for supplier in general_results.get('suppliers', []):
            stype = supplier.get('supplier_type', '')
            if stype == 'uk_wholesaler':
                uk_wholesaler_results.append(supplier)
            elif stype == 'uk_retail':
                uk_retail_results.append(supplier)
            elif stype == 'manufacturer':
                manufacturer_results.append(supplier)
            else:
                other_results.append(supplier)

        results = {
            'product_title': product_title,
            'uk_wholesalers': uk_wholesaler_results,
            'uk_retail': uk_retail_results,
            'manufacturers': manufacturer_results,
            'other': other_results,
            # Keep backward-compatible keys
            'alibaba': [s for s in manufacturer_results if s.get('platform') == 'Alibaba'],
            'global_sources': [s for s in manufacturer_results if s.get('platform') == 'Global Sources'],
            'all_suppliers': general_results.get('suppliers', [])
        }

        logger.info(f"✓ Total suppliers found: {len(results['all_suppliers'])} (1 API call)")
        logger.info(f"  UK Wholesalers: {len(uk_wholesaler_results)}, UK Retail: {len(uk_retail_results)}, "
                     f"Manufacturers: {len(manufacturer_results)}, Other: {len(other_results)}")

        return results

    def _parse_search_result(self, item: Dict[str, Any], platform: Optional[str] = None, product_keywords: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        Parse a Google Search result into supplier format.

        Args:
            item: Search result item
            platform: Platform name (optional)
            product_keywords: List of keywords the result must contain to be relevant

        Returns:
            Supplier dictionary or None
        """
        try:
            url = item.get('link', '')
            title = item.get('title', '')
            snippet = item.get('snippet', '')

            # Filter out non-product pages (articles, blogs, guides, help pages)
            url_lower = url.lower()
            title_lower = title.lower()

            # Skip URLs with these paths
            non_product_paths = [
                '/blog/', '/article/', '/help/', '/guide/', '/news/',
                '/resources/', '/how-to/', '/community/', '/forum/', '/post/',
                '/wiki/', '/faq/', '/support/', '/about/', '/company/',
                '/press/', '/media/', '/stories/', '/tips/', '/advice/',
                '/topic/', '/learn/', '/knowledge/', '/info/',
                '/product-insights/', '/insights/', '/trends/', '/industry/',
                '/sourcing-guide/', '/buying-guide/', '/wholesale-guide/'
            ]
            if any(path in url_lower for path in non_product_paths):
                logger.info(f"  ✗ FILTERED (non-product path): {url[:80]}")
                return None

            # Skip URLs on non-product subdomains
            non_product_subdomains = [
                'blog.', 'help.', 'resources.', 'news.', 'community.',
                'support.', 'forum.', 'wiki.', 'seller.', 'service.'
            ]
            if any(subdomain in url_lower for subdomain in non_product_subdomains):
                logger.info(f"  ✗ FILTERED (non-product subdomain): {url[:80]}")
                return None

            # Skip titles that indicate articles/guides
            article_title_patterns = [
                'how to', 'how do', 'what is', 'what are', 'why ',
                'guide to', 'tips for', 'best ways', 'ways to',
                '10 ways', '5 tips', 'complete guide', 'ultimate guide',
                'benefits of', 'advantages of', 'introduction to',
                'everything you need', 'top 10', 'top 5', 'best ', ' vs '
            ]
            if any(pattern in title_lower for pattern in article_title_patterns):
                logger.info(f"  ✗ FILTERED (article title): {title[:60]}")
                return None

            # Skip Alibaba non-product info pages
            if 'alibaba.com' in url_lower:
                alibaba_non_product = [
                    '/seller/', '/company/', '/member/',
                    'seller.alibaba.com', 'service.alibaba.com'
                ]
                if any(path in url_lower for path in alibaba_non_product):
                    logger.info(f"  ✗ FILTERED (Alibaba non-product): {url[:80]}")
                    return None

                # Accept product pages, showrooms, category pages, search results
                # Only reject if it's clearly not a product/listing page
                alibaba_valid_patterns = [
                    '/product/', 'product-detail', '.html',
                    '/offer/', '/suppliers/', '/showroom/',
                    '/wholesale/', '/trade/', '/catalog/',
                    '/search/', '/category/', '/promotion/',
                    '/item/', '/products/',
                ]
                if not any(x in url_lower for x in alibaba_valid_patterns):
                    # Still accept if URL has a path (not just homepage)
                    parsed = urlparse(url)
                    if parsed.path and parsed.path.strip('/') == '':
                        logger.info(f"  ✗ FILTERED (Alibaba homepage): {url[:80]}")
                        return None
                    # Has a path - likely a valid page, accept it
                    logger.debug(f"  Alibaba URL accepted (has path): {url[:80]}")

            # RELEVANCE CHECK: Ensure result matches the product we're searching for
            if product_keywords:
                # Combine title, snippet, and URL for checking
                result_text = f"{title_lower} {snippet.lower()} {url_lower}"

                # First try: exact keyword phrase match
                phrase_matches = [kw for kw in product_keywords if kw.lower() in result_text]

                if phrase_matches:
                    logger.debug(f"  Relevance OK - phrase matched: {phrase_matches}")
                else:
                    # Fallback: check individual words from keyword phrases
                    # Extract all unique words from keywords (e.g. "pet carrier" → {"pet", "carrier"})
                    keyword_words = set()
                    for kw in product_keywords:
                        for word in kw.lower().split():
                            if len(word) > 2:
                                keyword_words.add(word)

                    # Count how many individual keyword words appear in the result
                    word_matches = [w for w in keyword_words if w in result_text]
                    match_ratio = len(word_matches) / max(len(keyword_words), 1)

                    # Stricter check: require 50% match AND at least 3 matching words
                    # This prevents jute bags matching for dog pee pads
                    if match_ratio >= 0.5 and len(word_matches) >= 3:
                        logger.debug(f"  Relevance OK - word matched {len(word_matches)}/{len(keyword_words)}: {word_matches}")
                    else:
                        logger.info(f"  ✗ FILTERED (irrelevant - need 50%+ and 3+ words, got {len(word_matches)}/{len(keyword_words)}): {title[:50]}")
                        logger.debug(f"    Keywords: {product_keywords}, Words needed: {keyword_words}")
                        logger.debug(f"    Result text: {result_text[:100]}")
                        return None

            # Detect platform from URL using the known supplier site registry
            if not platform:
                parsed_url = urlparse(url)
                hostname = parsed_url.hostname or ''
                # Strip www. prefix for matching
                hostname_clean = hostname.removeprefix('www.')

                matched = False
                for domain, (site_name, site_type) in KNOWN_SUPPLIER_SITES.items():
                    if hostname_clean == domain or hostname_clean.endswith('.' + domain):
                        platform = site_name
                        matched = True
                        break

                if not matched:
                    # Accept results from the CSE — it only searches approved sites
                    # Use the hostname as the platform name
                    platform = hostname_clean.split('.')[0].title() if hostname_clean else 'Unknown'
                    logger.debug(f"  Unregistered but CSE-approved site: {hostname_clean}")

            # Extract pricing from snippet
            price_data = self._extract_price_from_snippet(snippet, title)

            supplier = {
                'platform': platform,
                'name': item.get('title', 'Unknown Supplier'),
                'url': url,
                'description': item.get('snippet', ''),
                'source': 'Google Custom Search',
                'supplier_type': self._classify_supplier_type(platform),
                'price_data': price_data,
            }

            if price_data:
                logger.info(f"    Price extracted: ${price_data['min_price']:.2f}-${price_data['max_price']:.2f}")

            return supplier

        except Exception as e:
            logger.warning(f"Failed to parse search result: {e}")
            return None

    def _classify_supplier_type(self, platform: str) -> str:
        """
        Classify supplier type based on platform name.

        Args:
            platform: Platform name

        Returns:
            Supplier type string
        """
        for domain, (name, stype) in KNOWN_SUPPLIER_SITES.items():
            if name == platform:
                return stype
        return 'wholesaler'

    def _extract_price_from_snippet(self, snippet: str, title: str) -> Optional[Dict[str, Any]]:
        """
        Extract supplier pricing from Google search snippet/title.

        Alibaba and other B2B platforms often show prices like:
        - "$1.50 - $3.00/piece"
        - "US $0.50-$2.00"
        - "£1.20 / Piece"
        - "MOQ: 100 pieces"

        Returns:
            Dict with min_price, max_price, currency, moq — or None
        """
        text = f"{title} {snippet}"

        result = {}

        # Pattern 1: Price range "$1.50 - $3.00" or "US $0.50-$2.00"
        range_pattern = r'(?:US\s*)?\$\s*(\d+(?:\.\d{1,2})?)\s*[-–]\s*(?:US\s*)?\$?\s*(\d+(?:\.\d{1,2})?)'
        match = re.search(range_pattern, text)
        if match:
            result['min_price'] = float(match.group(1))
            result['max_price'] = float(match.group(2))
            result['currency'] = 'USD'

        # Pattern 2: Single price "$1.50/piece" or "$2.00 / Piece"
        if not result:
            single_pattern = r'(?:US\s*)?\$\s*(\d+(?:\.\d{1,2})?)\s*(?:/\s*(?:piece|pcs?|unit|item))?'
            match = re.search(single_pattern, text, re.IGNORECASE)
            if match:
                price = float(match.group(1))
                if 0.01 < price < 500:  # Sanity check
                    result['min_price'] = price
                    result['max_price'] = price
                    result['currency'] = 'USD'

        # Pattern 3: GBP prices "£1.20"
        if not result:
            gbp_pattern = r'£\s*(\d+(?:\.\d{1,2})?)\s*[-–]?\s*(?:£?\s*(\d+(?:\.\d{1,2})?))?'
            match = re.search(gbp_pattern, text)
            if match:
                result['min_price'] = float(match.group(1))
                result['max_price'] = float(match.group(2)) if match.group(2) else float(match.group(1))
                result['currency'] = 'GBP'

        # Extract MOQ if present
        moq_pattern = r'(?:MOQ|Min(?:imum)?\s*(?:Order)?)\s*[:\s]*(\d+)\s*(?:pieces?|pcs?|units?|items?)?'
        moq_match = re.search(moq_pattern, text, re.IGNORECASE)
        if moq_match:
            result['moq'] = int(moq_match.group(1))

        # Also try "X Pieces (min" pattern for MOQ
        if 'moq' not in result:
            pieces_pattern = r'(\d+)\s*(?:pieces?|pcs)\s*\(?\s*(?:min|minimum)'
            moq_match = re.search(pieces_pattern, text, re.IGNORECASE)
            if moq_match:
                result['moq'] = int(moq_match.group(1))

        if result and 'min_price' in result:
            return result
        return None

    def estimate_cost(self, num_searches: int) -> float:
        """
        Estimate API cost.

        Google Custom Search API pricing:
        - First 100 searches/day: FREE
        - After 100: $5 per 1,000 queries

        Args:
            num_searches: Number of searches

        Returns:
            Estimated cost in USD
        """
        if num_searches <= 100:
            return 0.0

        paid_searches = num_searches - 100
        cost = (paid_searches / 1000) * 5.0
        return round(cost, 2)


# Singleton instance
_google_finder = None


def get_google_shopping_finder() -> GoogleShoppingFinder:
    """Get or create GoogleShoppingFinder instance."""
    global _google_finder
    if _google_finder is None:
        _google_finder = GoogleShoppingFinder()
    return _google_finder


# Test function
if __name__ == "__main__":
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    logging.basicConfig(level=logging.INFO)

    # Test search
    finder = GoogleShoppingFinder()

    # Example product
    product = "wireless bluetooth earbuds"

    print(f"\n{'='*60}")
    print(f"Testing Google Shopping Finder: {product}")
    print(f"{'='*60}\n")

    # Search multiple platforms
    results = finder.search_multiple_platforms(product)

    print(f"\nTotal suppliers found: {len(results['all_suppliers'])}")
    print(f"Alibaba: {len(results['alibaba'])}")
    print(f"Global Sources: {len(results['global_sources'])}")

    print(f"\n{'='*60}")
    print("Sample Results:")
    print(f"{'='*60}\n")

    for idx, supplier in enumerate(results['all_suppliers'][:5], 1):
        print(f"{idx}. {supplier['platform']}: {supplier['name']}")
        print(f"   URL: {supplier['url']}")
        print(f"   Description: {supplier['description'][:80]}...")
        print()
