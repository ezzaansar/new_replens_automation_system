"""Tests for Phase 5 forecasting methods."""

import pytest
import numpy as np

from src.phases.phase_5_forecasting import (
    simple_exponential_smoothing,
    holts_double_exponential,
    weighted_moving_average,
    select_best_method,
    compute_forecast_confidence,
    rank_to_daily_sales,
)


class TestSimpleExponentialSmoothing:
    def test_constant_series(self):
        series = [10.0] * 30
        result = simple_exponential_smoothing(series, alpha=0.3)
        # Returns array — check last value
        assert abs(float(result[-1]) - 10.0) < 0.1

    def test_trending_up(self):
        series = list(range(1, 31))
        result = simple_exponential_smoothing(series, alpha=0.3)
        assert float(result[-1]) > 15

    def test_single_value(self):
        result = simple_exponential_smoothing([5.0], alpha=0.3)
        assert float(result[-1]) == pytest.approx(5.0)

    def test_alpha_sensitivity(self):
        series = [10.0] * 20 + [20.0] * 10
        low_alpha = simple_exponential_smoothing(series, alpha=0.1)
        high_alpha = simple_exponential_smoothing(series, alpha=0.9)
        assert float(high_alpha[-1]) > float(low_alpha[-1])


class TestHoltsDoubleExponential:
    def test_constant_series(self):
        series = [10.0] * 30
        smoothed, level, trend = holts_double_exponential(series)
        assert abs(level - 10.0) < 0.5
        assert abs(trend) < 0.5

    def test_linear_trend(self):
        series = [float(i) for i in range(30)]
        smoothed, level, trend = holts_double_exponential(series)
        assert trend > 0

    def test_returns_tuple(self):
        result = holts_double_exponential([1.0, 2.0, 3.0, 4.0, 5.0])
        assert len(result) == 3


class TestWeightedMovingAverage:
    def test_constant_series(self):
        series = [10.0] * 30
        result = weighted_moving_average(series, window=7)
        assert abs(float(result[-1]) - 10.0) < 0.01

    def test_recent_values_weighted_more(self):
        series = [5.0] * 20 + [15.0] * 7
        result = weighted_moving_average(series, window=7)
        assert float(result[-1]) > 12

    def test_short_series(self):
        series = [10.0, 20.0, 30.0]
        result = weighted_moving_average(series, window=7)
        assert float(result[-1]) > 0


class TestSelectBestMethod:
    def test_selects_method(self):
        series = [float(i % 7 + 10) for i in range(60)]
        method_name = select_best_method(series)
        assert method_name in ('ses', 'holts', 'wma')

    def test_short_series_fallback(self):
        series = [10.0, 12.0, 8.0, 11.0, 9.0]
        method_name = select_best_method(series)
        assert method_name in ('ses', 'holts', 'wma')


class TestForecastConfidence:
    def test_confidence_intervals(self):
        series = [10.0 + np.random.normal(0, 1) for _ in range(30)]
        ci = compute_forecast_confidence(series, days_ahead=30)
        assert ci['ci_80_low'] < ci['ci_80_high']
        assert ci['ci_95_low'] < ci['ci_95_high']
        assert ci['ci_95_low'] <= ci['ci_80_low']
        assert ci['ci_95_high'] >= ci['ci_80_high']

    def test_wider_intervals_for_longer_horizon(self):
        series = [10.0 + np.random.normal(0, 2) for _ in range(30)]
        ci_short = compute_forecast_confidence(series, days_ahead=7)
        ci_long = compute_forecast_confidence(series, days_ahead=60)
        width_short = ci_short['ci_95_high'] - ci_short['ci_95_low']
        width_long = ci_long['ci_95_high'] - ci_long['ci_95_low']
        assert width_long > width_short


class TestRankToDailySales:
    def test_low_rank_high_sales(self):
        sales_low_rank = rank_to_daily_sales(1000, "Electronics")
        sales_high_rank = rank_to_daily_sales(100000, "Electronics")
        assert sales_low_rank > sales_high_rank

    def test_returns_positive(self):
        sales = rank_to_daily_sales(5000, "Home & Kitchen")
        assert sales > 0

    def test_unknown_category_uses_default(self):
        sales = rank_to_daily_sales(5000, "Unknown Category XYZ")
        assert sales > 0

    def test_zero_rank(self):
        sales = rank_to_daily_sales(0, "Electronics")
        assert sales >= 0
