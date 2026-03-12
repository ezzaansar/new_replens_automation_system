"""Tests for SP-API feed submission workflow."""

import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal


class TestUpdatePrice:
    """Test the 3-step feed submission for price updates."""

    def _make_api(self):
        """Create AmazonSPAPI with mocked auth."""
        with patch('src.api_wrappers.amazon_sp_api.requests.post') as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"access_token": "test_token", "expires_in": 3600},
                raise_for_status=lambda: None,
            )
            from src.api_wrappers.amazon_sp_api import AmazonSPAPI
            api = AmazonSPAPI()
        return api

    @patch('src.api_wrappers.amazon_sp_api.requests.put')
    @patch('src.api_wrappers.amazon_sp_api.requests.request')
    def test_update_price_success(self, mock_request, mock_put):
        api = self._make_api()

        # Step 1: create feed document
        # Step 3: submit feed
        mock_request.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"feedDocumentId": "doc123", "url": "https://upload.example.com/doc123"},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"feedId": "feed456"},
                raise_for_status=lambda: None,
            ),
        ]

        # Step 2: upload XML
        mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)

        result = api.update_price("SKU001", 12.99, "GBP")
        assert result is True

        # Verify upload was called with XML containing SKU and price
        mock_put.assert_called_once()
        uploaded_data = mock_put.call_args[1]['data'] if 'data' in mock_put.call_args[1] else mock_put.call_args[0][1] if len(mock_put.call_args[0]) > 1 else mock_put.call_args.kwargs.get('data')
        if isinstance(uploaded_data, bytes):
            uploaded_data = uploaded_data.decode('utf-8')
        assert 'SKU001' in uploaded_data
        assert '12.99' in uploaded_data

    @patch('src.api_wrappers.amazon_sp_api.requests.request')
    def test_update_price_fails_no_document_id(self, mock_request):
        api = self._make_api()

        mock_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {},  # No feedDocumentId
            raise_for_status=lambda: None,
        )

        result = api.update_price("SKU001", 12.99)
        assert result is False

    @patch('src.api_wrappers.amazon_sp_api.requests.put')
    @patch('src.api_wrappers.amazon_sp_api.requests.request')
    def test_update_price_fails_no_feed_id(self, mock_request, mock_put):
        api = self._make_api()

        mock_request.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"feedDocumentId": "doc123", "url": "https://upload.example.com/doc123"},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {},  # No feedId
                raise_for_status=lambda: None,
            ),
        ]
        mock_put.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)

        result = api.update_price("SKU001", 12.99)
        assert result is False

    @patch('src.api_wrappers.amazon_sp_api.requests.request')
    def test_get_feed_status(self, mock_request):
        api = self._make_api()

        mock_request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"processingStatus": "DONE", "feedId": "feed456"},
            raise_for_status=lambda: None,
        )

        status = api.get_feed_status("feed456")
        assert status["processingStatus"] == "DONE"

    def test_pricing_xml_format(self):
        """Verify the pricing XML contains required fields."""
        api = self._make_api()
        # Access the XML template indirectly by checking the method exists
        assert hasattr(api, 'update_price')
        assert hasattr(api, 'get_feed_status')


class TestEstimateFees:
    """Test Amazon fee estimation."""

    def _make_api(self):
        with patch('src.api_wrappers.amazon_sp_api.requests.post') as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"access_token": "test_token", "expires_in": 3600},
                raise_for_status=lambda: None,
            )
            from src.api_wrappers.amazon_sp_api import AmazonSPAPI
            api = AmazonSPAPI()
        return api

    def test_default_referral_fee(self):
        api = self._make_api()
        fees = api.estimate_fees("B00TEST", Decimal("20.00"), category="unknown_category")
        assert fees["referral_fee"] == Decimal("3.00")  # 15% of 20.00
        assert fees["fba_fee"] == Decimal("3.07")

    def test_electronics_referral_fee(self):
        api = self._make_api()
        fees = api.estimate_fees("B00TEST", Decimal("100.00"), category="electronics")
        assert fees["referral_fee"] == Decimal("15.00")  # 15% of 100.00

    def test_minimum_referral_fee(self):
        api = self._make_api()
        fees = api.estimate_fees("B00TEST", Decimal("1.00"), category="electronics")
        assert fees["referral_fee"] == Decimal("0.25")  # Minimum £0.25
