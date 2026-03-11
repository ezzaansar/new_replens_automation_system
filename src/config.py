"""
Configuration Management for Amazon Replens Automation System

Handles all configuration settings from environment variables with type safety
and validation using Pydantic.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, Union
from decimal import Decimal
import os


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings are validated and type-checked using Pydantic.
    """
    
    # ========================================================================
    # DATABASE CONFIGURATION
    # ========================================================================
    database_type: str = "sqlite"
    database_url: str = "sqlite:///./replens_automation.db"
    
    # ========================================================================
    # AMAZON SP-API CREDENTIALS
    # ========================================================================
    amazon_client_id: str
    amazon_client_secret: str
    amazon_refresh_token: str
    amazon_region: str = "NA"  # NA, EU, FE
    amazon_seller_id: str
    
    # ========================================================================
    # KEEPA API CONFIGURATION
    # ========================================================================
    keepa_api_key: str
    keepa_domain: str = "US"  # Country code: US, GB, DE, FR, JP, CA, IT, ES, IN, MX
    
    # ========================================================================
    # OPENAI API CONFIGURATION (Optional)
    # ========================================================================
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4"

    # ========================================================================
    # GOOGLE APIS CONFIGURATION (Optional)
    # ========================================================================
    google_api_key: Optional[str] = None
    google_search_engine_id: Optional[str] = None  # Custom Search Engine ID (cx)

    # ========================================================================
    # REPRICING TOOL INTEGRATION (Optional)
    # ========================================================================
    eva_guru_api_key: Optional[str] = None
    bqool_api_key: Optional[str] = None
    
    # ========================================================================
    # NOTIFICATION CONFIGURATION
    # ========================================================================
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_email_to: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    
    # ========================================================================
    # SYSTEM CONFIGURATION
    # ========================================================================
    log_level: str = "INFO"
    log_file: str = "logs/replens_automation.log"
    
    # Profitability Thresholds
    min_profit_margin: float = 0.25  # 25%
    min_roi: float = 1.0  # 100%
    min_sales_velocity: int = 10  # units/month
    
    # Pricing Configuration
    target_buy_box_win_rate: float = 0.90  # 90%
    price_adjustment_frequency: str = "hourly"
    price_adjustment_amount: Decimal = Decimal("0.01")
    max_price_multiplier: float = 1.5  # Maximum price = cost × 1.5
    min_price_change_percent: float = 0.01  # Only reprice if change > 1%
    
    # Inventory Configuration
    inventory_turnover_target: int = 4  # 4x per month
    safety_stock_days: int = 7
    reorder_point_multiplier: float = 1.5
    
    # Forecasting Configuration
    forecast_days_ahead: int = 30
    seasonality_adjustment: bool = True
    promotion_impact_factor: float = 1.5
    
    # ========================================================================
    # SCHEDULER CONFIGURATION
    # ========================================================================
    discovery_run_time: str = "02:00"
    repricing_run_frequency: str = "hourly"
    inventory_check_frequency: str = "daily"
    forecast_update_frequency: str = "daily"
    dashboard_refresh_interval: int = 300  # seconds
    
    # ========================================================================
    # INFRASTRUCTURE CONFIGURATION
    # ========================================================================
    keepa_rate_limit: int = 10  # requests/second
    amazon_rate_limit: int = 5  # requests/second
    
    # Cache Configuration
    cache_enabled: bool = True
    cache_ttl: int = 3600  # seconds
    
    # ========================================================================
    # SECURITY CONFIGURATION
    # ========================================================================
    api_timeout: int = 30  # seconds
    api_retries: int = 3
    api_backoff_factor: float = 2.0
    
    # ========================================================================
    # DEVELOPMENT/TESTING
    # ========================================================================
    debug_mode: bool = False
    test_mode: bool = False
    dry_run: bool = False

    @field_validator('keepa_domain', mode='before')
    @classmethod
    def normalize_keepa_domain(cls, v):
        """Normalize Keepa domain to uppercase country code string."""
        if isinstance(v, int):
            domain_map = {
                1: 'US',
                2: 'GB',
                3: 'DE',
                4: 'FR',
                5: 'JP',
                6: 'CA',
                8: 'IT',
                9: 'ES',
                10: 'IN',
                11: 'MX',
            }
            if v in domain_map:
                return domain_map[v]
            raise ValueError(f"Invalid keepa_domain integer: {v}")
        if isinstance(v, str):
            v_upper = v.upper()
            if v_upper == 'UK':
                return 'GB'
            return v_upper
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


# Load settings from environment
settings = Settings()


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# Amazon Fee Estimates (as of 2024)
AMAZON_REFERRAL_FEES = {
    "default": 0.15,  # 15%
    "apparel": 0.17,
    "electronics": 0.15,
    "home": 0.15,
    "home & kitchen": 0.15,
    "toys": 0.15,
    "toys & games": 0.15,
    "sports": 0.15,
    "sports & outdoors": 0.15,
    "beauty": 0.15,
    "health & personal care": 0.15,
    "musical instruments & dj": 0.15,
    "musical instruments": 0.15,
    "pet supplies": 0.15,
    "office products": 0.15,
    "automotive": 0.12,
    "books": 0.15,
    "computers & accessories": 0.07,
}

# UK FBA Fulfillment Fees (GBP) — approximate schedule
AMAZON_FBA_FEES = {
    "small_standard": {
        "weight_limit": 0.46,  # kg
        "fee": 2.15  # GBP
    },
    "large_standard": {
        "weight_limit": 12.0,  # kg
        "fee": 3.07  # GBP
    },
    "small_oversize": {
        "weight_limit": 30.0,  # kg
        "fee": 5.80  # GBP
    },
    "large_oversize": {
        "weight_limit": 60.0,  # kg
        "fee": 9.44  # GBP
    },
    "special_oversize": {
        "weight_limit": float('inf'),
        "fee": 12.50  # GBP
    }
}

# Default FBA fee when product weight/dimensions are unknown
AMAZON_FBA_FEE_DEFAULT = Decimal("3.07")  # Large standard (most common)

# Category-Specific Sales Estimation Curves
# Uses power-law approximation: estimated_monthly_sales = multiplier * (rank ** exponent)
# Based on publicly available research for UK marketplace
CATEGORY_SALES_CURVES = {
    "Electronics": (120000, -0.80),
    "Computers & Accessories": (120000, -0.80),
    "Home & Kitchen": (80000, -0.75),
    "Home": (80000, -0.75),
    "Musical Instruments & DJ": (20000, -0.70),
    "Musical Instruments": (20000, -0.70),
    "Sports & Outdoors": (60000, -0.75),
    "Beauty": (70000, -0.75),
    "Toys & Games": (90000, -0.78),
    "Pet Supplies": (50000, -0.75),
    "Office Products": (40000, -0.72),
    "Automotive": (35000, -0.70),
    "Health & Personal Care": (65000, -0.75),
    "Books": (100000, -0.80),
    "default": (50000, -0.75),
}

# Sales Rank Thresholds for Underserved Detection
SALES_RANK_THRESHOLDS = {
    "excellent": 10000,
    "good": 50000,
    "moderate": 100000,
    "poor": 500000,
}

# Seller Count Thresholds
SELLER_COUNT_THRESHOLDS = {
    "very_low": 2,
    "low": 5,
    "moderate": 10,
    "high": 20,
}

# Price Stability Thresholds (standard deviation)
PRICE_STABILITY_THRESHOLDS = {
    "very_stable": 2.0,
    "stable": 5.0,
    "moderate": 10.0,
    "volatile": 20.0,
}

# Forecast Models
FORECAST_MODELS = {
    "prophet": "Facebook Prophet (time series)",
    "xgboost": "XGBoost (gradient boosting)",
    "arima": "ARIMA (autoregressive)",
    "exponential_smoothing": "Exponential Smoothing",
}

# API Endpoints
AMAZON_SP_API_ENDPOINTS = {
    "NA": "https://sellingpartnerapi-na.amazon.com",
    "EU": "https://sellingpartnerapi-eu.amazon.com",
    "FE": "https://sellingpartnerapi-fe.amazon.com",
}

KEEPA_API_ENDPOINT = "https://api.keepa.com"

# Status Constants
PRODUCT_STATUS = ["active", "archived", "rejected"]
SUPPLIER_STATUS = ["active", "inactive", "blacklisted"]
PO_STATUS = ["pending", "confirmed", "shipped", "received", "cancelled"]

# Notification Templates
NOTIFICATION_TEMPLATES = {
    "low_stock": "Product {asin} ({title}) is running low on stock. Current: {current_stock}, Reorder Point: {reorder_point}",
    "new_opportunity": "New opportunity found: {title} (ASIN: {asin}). Opportunity Score: {score}/100",
    "price_drop": "Price drop detected for {asin}. Current: ${current_price}, Previous: ${previous_price}",
    "buy_box_lost": "Lost Buy Box for {asin}. Competitor price: ${competitor_price}",
    "margin_alert": "Profit margin below target for {asin}. Current: {margin}%, Target: {target_margin}%",
}


def get_settings() -> Settings:
    """Get the current settings instance."""
    return settings


def validate_settings():
    """Validate that all required settings are configured."""
    required_fields = [
        "amazon_client_id",
        "amazon_client_secret",
        "amazon_refresh_token",
        "amazon_seller_id",
        "keepa_api_key",
    ]
    
    missing = []
    for field in required_fields:
        if not getattr(settings, field, None):
            missing.append(field)
    
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")
    
    return True


if __name__ == "__main__":
    # Print current configuration (without sensitive data)
    print("Amazon Replens Automation System - Configuration")
    print("=" * 60)
    print(f"Database: {settings.database_type}")
    print(f"Amazon Region: {settings.amazon_region}")
    print(f"Min Profit Margin: {settings.min_profit_margin * 100}%")
    print(f"Min ROI: {settings.min_roi * 100}%")
    print(f"Target Buy Box Win Rate: {settings.target_buy_box_win_rate * 100}%")
    print(f"Forecast Days Ahead: {settings.forecast_days_ahead}")
    print(f"Debug Mode: {settings.debug_mode}")
    print(f"Dry Run: {settings.dry_run}")
