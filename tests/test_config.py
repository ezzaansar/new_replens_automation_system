"""Tests for configuration and constants."""

import pytest
from decimal import Decimal

from src.config import (
    AMAZON_REFERRAL_FEES,
    AMAZON_FBA_FEES,
    AMAZON_FBA_FEE_DEFAULT,
    WHOLESALE_COST_RATIOS,
    ESTIMATED_SHIPPING_COSTS,
    CATEGORY_SALES_CURVES,
    SALES_RANK_THRESHOLDS,
    FORECAST_MODELS,
)


class TestReferralFees:
    def test_default_fee_exists(self):
        assert "default" in AMAZON_REFERRAL_FEES
        assert AMAZON_REFERRAL_FEES["default"] == 0.15

    def test_all_fees_in_valid_range(self):
        for category, fee in AMAZON_REFERRAL_FEES.items():
            assert 0 < fee < 1, f"Invalid fee for {category}: {fee}"

    def test_known_categories(self):
        assert "electronics" in AMAZON_REFERRAL_FEES
        assert "beauty" in AMAZON_REFERRAL_FEES
        assert "automotive" in AMAZON_REFERRAL_FEES


class TestFBAFees:
    def test_default_fee(self):
        assert AMAZON_FBA_FEE_DEFAULT == Decimal("3.07")

    def test_fee_tiers_ordered(self):
        tiers = list(AMAZON_FBA_FEES.values())
        fees = [t["fee"] for t in tiers]
        assert fees == sorted(fees), "FBA fees should increase with size"


class TestWholesaleRatios:
    def test_default_ratio_exists(self):
        assert "default" in WHOLESALE_COST_RATIOS
        assert 0 < WHOLESALE_COST_RATIOS["default"] < 1

    def test_ratios_in_valid_range(self):
        for category, ratio in WHOLESALE_COST_RATIOS.items():
            assert 0.1 <= ratio <= 0.6, f"Suspicious ratio for {category}: {ratio}"

    def test_electronics_higher_than_beauty(self):
        assert WHOLESALE_COST_RATIOS["Electronics"] > WHOLESALE_COST_RATIOS["Beauty"]


class TestShippingCosts:
    def test_default_exists(self):
        assert "default" in ESTIMATED_SHIPPING_COSTS
        assert ESTIMATED_SHIPPING_COSTS["default"] > 0

    def test_china_cheaper_than_express(self):
        assert ESTIMATED_SHIPPING_COSTS["china_standard"] < ESTIMATED_SHIPPING_COSTS["china_express"]

    def test_uk_cheapest(self):
        assert ESTIMATED_SHIPPING_COSTS["uk_domestic"] < ESTIMATED_SHIPPING_COSTS["china_standard"]


class TestSalesCurves:
    def test_default_exists(self):
        assert "default" in CATEGORY_SALES_CURVES

    def test_curve_format(self):
        for category, (multiplier, exponent) in CATEGORY_SALES_CURVES.items():
            assert multiplier > 0, f"Invalid multiplier for {category}"
            assert exponent < 0, f"Exponent should be negative for {category}"


class TestForecastModels:
    def test_actual_models_listed(self):
        assert "ses" in FORECAST_MODELS or "exponential_smoothing" in FORECAST_MODELS
