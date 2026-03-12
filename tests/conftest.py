"""
Shared test fixtures for the Amazon Replens Automation test suite.
"""

import os
import pytest
from decimal import Decimal
from datetime import datetime

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DATABASE_TYPE"] = "sqlite"

# Dummy API keys for tests (won't hit real APIs)
os.environ.setdefault("AMAZON_CLIENT_ID", "test_client_id")
os.environ.setdefault("AMAZON_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("AMAZON_REFRESH_TOKEN", "test_refresh_token")
os.environ.setdefault("AMAZON_SELLER_ID", "test_seller_id")
os.environ.setdefault("KEEPA_API_KEY", "test_keepa_key")

from src.database import Base, engine, SessionLocal, Product, Supplier, ProductSupplier, Inventory, PurchaseOrder, Performance


@pytest.fixture
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_product(db_session):
    """Create a sample product."""
    product = Product(
        asin="B00TEST001",
        title="Test Guitar Tuner Clip-On",
        category="Musical Instruments",
        current_price=Decimal("12.99"),
        sales_rank=5000,
        estimated_monthly_sales=150,
        profit_potential=Decimal("3.50"),
        num_sellers=5,
        num_fba_sellers=3,
        is_underserved=True,
        opportunity_score=75.0,
        status="active",
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture
def sample_supplier(db_session):
    """Create a sample supplier."""
    supplier = Supplier(
        name="Alibaba - Test Supplier",
        website="https://www.alibaba.com/test",
        min_order_qty=50,
        lead_time_days=14,
        reliability_score=50.0,
        on_time_delivery_rate=0.85,
        status="active",
    )
    db_session.add(supplier)
    db_session.commit()
    return supplier


@pytest.fixture
def sample_product_supplier(db_session, sample_product, sample_supplier):
    """Create a sample product-supplier link with costs."""
    ps = ProductSupplier(
        asin=sample_product.asin,
        supplier_id=sample_supplier.supplier_id,
        supplier_cost=Decimal("3.90"),
        shipping_cost=Decimal("1.50"),
        total_cost=Decimal("5.40"),
        estimated_profit=Decimal("2.64"),
        profit_margin=0.2032,
        roi=0.4889,
        is_preferred=True,
    )
    db_session.add(ps)
    db_session.commit()
    return ps


@pytest.fixture
def sample_inventory(db_session, sample_product):
    """Create sample inventory record."""
    inv = Inventory(
        asin=sample_product.asin,
        current_stock=100,
        reserved=5,
        available=95,
        reorder_point=30,
        safety_stock=15,
        days_of_supply=20.0,
        needs_reorder=False,
    )
    db_session.add(inv)
    db_session.commit()
    return inv
