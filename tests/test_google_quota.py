"""Tests for Google API quota tracking."""

import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestQuotaTracking:
    """Test persistent quota tracking for Google Custom Search API."""

    def _make_finder(self, quota_file):
        """Create a GoogleShoppingFinder with mocked config and custom quota file."""
        with patch('src.api_wrappers.google_shopping_finder.settings') as mock_settings:
            mock_settings.google_api_key = "test_key"
            mock_settings.google_search_engine_id = "test_cx"
            from src.api_wrappers.google_shopping_finder import GoogleShoppingFinder
            finder = GoogleShoppingFinder.__new__(GoogleShoppingFinder)
            finder.api_key = "test_key"
            finder.cx = "test_cx"
            finder.base_url = "https://www.googleapis.com/customsearch/v1"
        # Override quota file path
        finder._get_quota_file = lambda: quota_file
        return finder

    def test_load_quota_fresh(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        quota = finder._load_quota()
        assert quota['queries_used'] == 0
        assert quota['limit'] == 100
        assert quota['date'] == datetime.now().strftime('%Y-%m-%d')

    def test_save_and_load_quota(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        finder._save_quota({'date': '2026-03-13', 'queries_used': 42, 'limit': 100})
        # Reload
        with open(quota_file, 'r') as f:
            data = json.load(f)
        assert data['queries_used'] == 42

    def test_quota_resets_daily(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        # Save yesterday's quota
        finder._save_quota({'date': '2020-01-01', 'queries_used': 99, 'limit': 100})

        # Load should reset because date doesn't match today
        quota = finder._load_quota()
        assert quota['queries_used'] == 0

    def test_check_quota_ok(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        finder._save_quota({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'queries_used': 50,
            'limit': 100,
        })
        assert finder._check_quota() is True

    def test_check_quota_exhausted(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        finder._save_quota({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'queries_used': 100,
            'limit': 100,
        })
        assert finder._check_quota() is False

    def test_record_query_increments(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        finder._save_quota({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'queries_used': 5,
            'limit': 100,
        })
        finder._record_query()

        quota = finder._load_quota()
        assert quota['queries_used'] == 6

    def test_check_quota_warns_when_low(self, tmp_path):
        quota_file = str(tmp_path / "quota.json")
        finder = self._make_finder(quota_file)

        finder._save_quota({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'queries_used': 95,
            'limit': 100,
        })
        # Should return True (still has quota) but log a warning
        assert finder._check_quota() is True


class TestEstimateCost:
    """Test API cost estimation."""

    def _make_finder(self):
        with patch('src.api_wrappers.google_shopping_finder.settings') as mock_settings:
            mock_settings.google_api_key = "test_key"
            mock_settings.google_search_engine_id = "test_cx"
            from src.api_wrappers.google_shopping_finder import GoogleShoppingFinder
            finder = GoogleShoppingFinder.__new__(GoogleShoppingFinder)
            finder.api_key = "test_key"
            finder.cx = "test_cx"
            finder.base_url = "https://www.googleapis.com/customsearch/v1"
        return finder

    def test_free_tier(self):
        finder = self._make_finder()
        assert finder.estimate_cost(50) == 0.0
        assert finder.estimate_cost(100) == 0.0

    def test_paid_tier(self):
        finder = self._make_finder()
        # 200 searches = 100 free + 100 paid = 100/1000 * $5 = $0.50
        assert finder.estimate_cost(200) == 0.50

    def test_large_volume(self):
        finder = self._make_finder()
        # 1100 searches = 100 free + 1000 paid = $5.00
        assert finder.estimate_cost(1100) == 5.0


class TestRateLimiter:
    """Test the thread-safe rate limiter."""

    def test_first_call_no_delay(self):
        from src.api_wrappers.google_shopping_finder import RateLimiter
        import time

        limiter = RateLimiter(max_calls_per_second=10.0)
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        # First call should not wait
        assert elapsed < 0.2

    def test_enforces_minimum_interval(self):
        from src.api_wrappers.google_shopping_finder import RateLimiter
        import time

        limiter = RateLimiter(max_calls_per_second=5.0)  # 0.2s interval
        limiter.wait()
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        # Second call should wait ~0.2s
        assert elapsed >= 0.15


class TestUKSupplierSiteRegistry:
    """Test the known supplier site registry."""

    def test_all_uk_wholesalers_registered(self):
        from src.api_wrappers.google_shopping_finder import KNOWN_SUPPLIER_SITES
        # Check key UK wholesalers
        assert 'booker.co.uk' in KNOWN_SUPPLIER_SITES
        assert 'dcsgroup.com' in KNOWN_SUPPLIER_SITES
        assert 'costco.co.uk' in KNOWN_SUPPLIER_SITES
        assert 'bestwaywholesale.co.uk' in KNOWN_SUPPLIER_SITES

    def test_uk_retail_sites_registered(self):
        from src.api_wrappers.google_shopping_finder import KNOWN_SUPPLIER_SITES
        assert 'boots.com' in KNOWN_SUPPLIER_SITES
        assert 'argos.co.uk' in KNOWN_SUPPLIER_SITES
        assert 'smythstoys.com' in KNOWN_SUPPLIER_SITES

    def test_manufacturer_sites_still_registered(self):
        from src.api_wrappers.google_shopping_finder import KNOWN_SUPPLIER_SITES
        assert 'alibaba.com' in KNOWN_SUPPLIER_SITES
        assert 'globalsources.com' in KNOWN_SUPPLIER_SITES

    def test_supplier_types_correct(self):
        from src.api_wrappers.google_shopping_finder import KNOWN_SUPPLIER_SITES
        _, stype = KNOWN_SUPPLIER_SITES['booker.co.uk']
        assert stype == 'uk_wholesaler'
        _, stype = KNOWN_SUPPLIER_SITES['boots.com']
        assert stype == 'uk_retail'
        _, stype = KNOWN_SUPPLIER_SITES['alibaba.com']
        assert stype == 'manufacturer'
        _, stype = KNOWN_SUPPLIER_SITES['esources.co.uk']
        assert stype == 'uk_directory'


class TestParseSearchResultPlatformDetection:
    """Test that _parse_search_result correctly identifies UK wholesaler sites."""

    def _make_finder(self):
        with patch('src.api_wrappers.google_shopping_finder.settings') as mock_settings:
            mock_settings.google_api_key = "test_key"
            mock_settings.google_search_engine_id = "test_cx"
            from src.api_wrappers.google_shopping_finder import GoogleShoppingFinder, RateLimiter
            finder = GoogleShoppingFinder.__new__(GoogleShoppingFinder)
            finder.api_key = "test_key"
            finder.cx = "test_cx"
            finder.base_url = "https://www.googleapis.com/customsearch/v1"
            finder._rate_limiter = RateLimiter(max_calls_per_second=10.0)
        return finder

    def test_detects_uk_wholesaler(self):
        finder = self._make_finder()
        item = {
            'link': 'https://www.booker.co.uk/products/nivea-cream-150ml',
            'title': 'Nivea Cream 150ml',
            'snippet': 'Wholesale price for Nivea Cream 150ml',
        }
        result = finder._parse_search_result(item)
        assert result is not None
        assert result['platform'] == 'Booker Wholesale'
        assert result['supplier_type'] == 'uk_wholesaler'

    def test_detects_uk_retail(self):
        finder = self._make_finder()
        item = {
            'link': 'https://www.boots.com/nivea-cream-150ml',
            'title': 'Nivea Cream 150ml',
            'snippet': 'Buy Nivea Cream 150ml at Boots',
        }
        result = finder._parse_search_result(item)
        assert result is not None
        assert result['platform'] == 'Boots'
        assert result['supplier_type'] == 'uk_retail'

    def test_detects_manufacturer(self):
        finder = self._make_finder()
        item = {
            'link': 'https://www.alibaba.com/product-detail/cream-wholesale_123.html',
            'title': 'Cream Wholesale - Alibaba',
            'snippet': 'Wholesale cream from manufacturer',
        }
        result = finder._parse_search_result(item)
        assert result is not None
        assert result['platform'] == 'Alibaba'
        assert result['supplier_type'] == 'manufacturer'

    def test_www_prefix_stripped_correctly(self):
        """Ensure www. prefix doesn't break wholesale-deals matching."""
        finder = self._make_finder()
        item = {
            'link': 'https://www.wholesale-deals.co.uk/product/123',
            'title': 'Test Product',
            'snippet': 'Wholesale deals on test products',
        }
        result = finder._parse_search_result(item)
        assert result is not None
        assert result['platform'] == 'Wholesale Deals'
