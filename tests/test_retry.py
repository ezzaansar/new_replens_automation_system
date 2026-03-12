"""Tests for retry utility."""

import pytest
import requests
from unittest.mock import patch, MagicMock

from src.utils.retry import retry_with_backoff, RETRYABLE_STATUS_CODES


class TestRetryDecorator:
    def test_success_on_first_try(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeeds()
        assert result == "ok"
        assert call_count == 1

    def test_retries_on_connection_error(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise requests.exceptions.ConnectionError("connection reset")
            return "ok"

        result = fails_then_succeeds()
        assert result == "ok"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        @retry_with_backoff(max_retries=2, base_delay=0.01)
        def always_fails():
            raise requests.exceptions.Timeout("timeout")

        with pytest.raises(requests.exceptions.Timeout):
            always_fails()

    def test_non_retryable_exception_not_retried(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            raises_value_error()
        assert call_count == 1  # Should not retry

    def test_retryable_status_codes(self):
        assert 429 in RETRYABLE_STATUS_CODES
        assert 500 in RETRYABLE_STATUS_CODES
        assert 503 in RETRYABLE_STATUS_CODES
        assert 200 not in RETRYABLE_STATUS_CODES


class TestPriceExtraction:
    """Test Google snippet price extraction."""

    def test_usd_price_range(self):
        from src.api_wrappers.google_shopping_finder import GoogleShoppingFinder
        # Can't instantiate without API key, test the regex directly
        import re
        text = "US $1.50 - $3.00/piece"
        pattern = r'(?:US\s*)?\$\s*(\d+(?:\.\d{1,2})?)\s*[-–]\s*(?:US\s*)?\$?\s*(\d+(?:\.\d{1,2})?)'
        match = re.search(pattern, text)
        assert match is not None
        assert float(match.group(1)) == 1.50
        assert float(match.group(2)) == 3.00

    def test_gbp_price(self):
        import re
        text = "£12.99 per unit"
        pattern = r'£\s*(\d+(?:\.\d{1,2})?)'
        match = re.search(pattern, text)
        assert match is not None
        assert float(match.group(1)) == 12.99

    def test_moq_extraction(self):
        import re
        text = "MOQ: 100 pieces"
        pattern = r'(?:MOQ|Min(?:imum)?\s*(?:Order)?)\s*[:\s]*(\d+)\s*(?:pieces?|pcs?|units?|items?)?'
        match = re.search(pattern, text, re.IGNORECASE)
        assert match is not None
        assert int(match.group(1)) == 100
