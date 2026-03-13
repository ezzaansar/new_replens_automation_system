"""Tests for Phase 3 automated cost estimation."""

import pytest
from decimal import Decimal

from src.phases.phase_3_sourcing_google import GoogleSupplierMatchingEngine


@pytest.fixture
def engine():
    """Create sourcing engine without Google API."""
    return GoogleSupplierMatchingEngine(use_google=False)


class MockProduct:
    """Mock product for testing."""
    def __init__(self, price=15.99, category="Musical Instruments", asin="TEST001"):
        self.current_price = Decimal(str(price))
        self.category = category
        self.asin = asin


class TestEstimateSupplierCost:
    def test_category_based_estimation(self, engine):
        product = MockProduct(price=15.99, category="Musical Instruments")
        info = {"platform": "Alibaba", "price_data": None}
        cost = engine._estimate_supplier_cost(product, info)

        assert cost["source"] == "estimated"
        assert cost["supplier_cost"] > 0
        assert cost["shipping_cost"] > 0
        assert cost["total_cost"] == cost["supplier_cost"] + cost["shipping_cost"]

    def test_extracted_price_used_when_available(self, engine):
        product = MockProduct(price=20.00)
        info = {
            "platform": "Alibaba",
            "price_data": {"min_price": 3.00, "max_price": 5.00, "currency": "USD"},
        }
        cost = engine._estimate_supplier_cost(product, info)

        assert cost["source"] == "extracted"
        # Midpoint $4 * 0.79 = £3.16
        assert float(cost["supplier_cost"]) == pytest.approx(3.16, abs=0.01)

    def test_extracted_price_rejected_if_too_high(self, engine):
        product = MockProduct(price=10.00)
        info = {
            "platform": "Alibaba",
            "price_data": {"min_price": 8.00, "max_price": 10.00, "currency": "USD"},
        }
        cost = engine._estimate_supplier_cost(product, info)

        # $9 * 0.79 = £7.11 which is > 60% of £10, so should fall back to category
        assert cost["source"] == "estimated"

    def test_zero_price_product(self, engine):
        product = MockProduct(price=0)
        info = {"platform": "Alibaba", "price_data": None}
        cost = engine._estimate_supplier_cost(product, info)

        assert cost["total_cost"] == Decimal("0")
        assert cost["source"] == "none"

    def test_shipping_varies_by_platform(self, engine):
        product = MockProduct(price=20.00)
        alibaba = engine._estimate_supplier_cost(product, {"platform": "Alibaba", "price_data": None})
        unknown = engine._estimate_supplier_cost(product, {"platform": "", "price_data": None})

        # Both should have shipping but from different tiers
        assert alibaba["shipping_cost"] > 0
        assert unknown["shipping_cost"] > 0

    def test_uk_wholesaler_gets_domestic_shipping(self, engine):
        product = MockProduct(price=20.00)
        uk = engine._estimate_supplier_cost(product, {
            "platform": "Booker Wholesale",
            "supplier_type": "uk_wholesaler",
            "price_data": None,
        })
        china = engine._estimate_supplier_cost(product, {
            "platform": "Alibaba",
            "supplier_type": "manufacturer",
            "price_data": None,
        })

        # UK domestic shipping (£0.80) should be cheaper than China (£1.50)
        assert uk["shipping_cost"] < china["shipping_cost"]
        assert uk["shipping_cost"] == Decimal("0.80")

    def test_uk_retail_gets_domestic_shipping(self, engine):
        product = MockProduct(price=20.00)
        retail = engine._estimate_supplier_cost(product, {
            "platform": "Boots",
            "supplier_type": "uk_retail",
            "price_data": None,
        })
        assert retail["shipping_cost"] == Decimal("0.80")


class TestCalculateProfitability:
    def test_profitable_product(self, engine):
        prof = engine._calculate_profitability(20.00, Decimal("6.00"), "Musical Instruments")

        assert prof["estimated_profit"] > 0
        assert prof["profit_margin"] > 0
        assert prof["roi"] > 0

    def test_unprofitable_product(self, engine):
        prof = engine._calculate_profitability(5.00, Decimal("10.00"), "Electronics")

        assert prof["estimated_profit"] < 0
        assert prof["profit_margin"] < 0

    def test_zero_price(self, engine):
        prof = engine._calculate_profitability(0, Decimal("5.00"), "Home")

        assert prof["estimated_profit"] == Decimal("0")
        assert prof["profit_margin"] == 0.0

    def test_category_affects_fees(self, engine):
        # Automotive has 12% referral, default has 15%
        auto = engine._calculate_profitability(50.00, Decimal("15.00"), "automotive")
        default = engine._calculate_profitability(50.00, Decimal("15.00"), "unknown_cat")

        # Automotive should have higher profit due to lower referral fee
        assert auto["estimated_profit"] > default["estimated_profit"]
