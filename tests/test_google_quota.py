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
