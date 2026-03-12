"""Tests for database models and operations."""

import pytest
from decimal import Decimal
from datetime import datetime

from src.database import Product, Supplier, ProductSupplier, Inventory, PurchaseOrder, Performance, DatabaseOperations


class TestProductModel:
    def test_create_product(self, db_session):
        product = Product(
            asin="B00NEWPROD",
            title="New Product",
            category="Electronics",
            current_price=Decimal("29.99"),
            status="active",
        )
        db_session.add(product)
        db_session.commit()

        result = db_session.query(Product).filter(Product.asin == "B00NEWPROD").first()
        assert result is not None
        assert result.title == "New Product"
        assert result.current_price == Decimal("29.99")

    def test_product_defaults(self, db_session):
        product = Product(asin="B00DFLT01", title="Default Test", category="Home")
        db_session.add(product)
        db_session.commit()

        assert product.status == "active"
        assert product.opportunity_score == 0.0
        assert product.is_underserved is False
        assert product.num_sellers == 0

    def test_product_relationships(self, sample_product, sample_product_supplier, db_session):
        product = db_session.query(Product).filter(Product.asin == sample_product.asin).first()
        assert len(product.suppliers) == 1
        assert product.suppliers[0].supplier_cost == Decimal("3.90")


class TestSupplierModel:
    def test_create_supplier(self, db_session):
        supplier = Supplier(
            name="Test Wholesaler",
            website="https://example.com",
            min_order_qty=25,
            lead_time_days=7,
        )
        db_session.add(supplier)
        db_session.commit()

        result = db_session.query(Supplier).filter(Supplier.name == "Test Wholesaler").first()
        assert result is not None
        assert result.min_order_qty == 25

    def test_supplier_defaults(self, db_session):
        supplier = Supplier(name="Default Supplier")
        db_session.add(supplier)
        db_session.commit()

        assert supplier.status == "active"
        assert supplier.reliability_score == 0.0
        assert supplier.total_orders == 0


class TestProductSupplierModel:
    def test_profitability_fields(self, sample_product_supplier):
        assert sample_product_supplier.supplier_cost == Decimal("3.90")
        assert sample_product_supplier.shipping_cost == Decimal("1.50")
        assert sample_product_supplier.total_cost == Decimal("5.40")
        assert sample_product_supplier.profit_margin > 0
        assert sample_product_supplier.roi > 0
        assert sample_product_supplier.is_preferred is True

    def test_zero_cost_detection(self, db_session, sample_product, sample_supplier):
        ps = ProductSupplier(
            asin=sample_product.asin,
            supplier_id=sample_supplier.supplier_id,
            supplier_cost=Decimal("0"),
            total_cost=Decimal("0"),
        )
        db_session.add(ps)
        db_session.commit()

        zero_cost = db_session.query(ProductSupplier).filter(
            ProductSupplier.supplier_cost <= 0
        ).count()
        assert zero_cost >= 1


class TestInventoryModel:
    def test_inventory_fields(self, sample_inventory):
        assert sample_inventory.current_stock == 100
        assert sample_inventory.available == 95
        assert sample_inventory.needs_reorder is False

    def test_reorder_flag(self, db_session, sample_product):
        inv = Inventory(
            asin=sample_product.asin,
            current_stock=5,
            reorder_point=30,
            needs_reorder=True,
        )
        db_session.add(inv)
        db_session.commit()

        reorder_items = db_session.query(Inventory).filter(
            Inventory.needs_reorder == True
        ).all()
        assert len(reorder_items) == 1


class TestDatabaseOperations:
    def test_get_underserved_products(self, db_session, sample_product):
        ops = DatabaseOperations()
        products = ops.get_underserved_products(db_session, limit=10)
        assert len(products) == 1
        assert products[0].asin == sample_product.asin

    def test_get_product(self, db_session, sample_product):
        ops = DatabaseOperations()
        product = ops.get_product(db_session, sample_product.asin)
        assert product is not None
        assert product.title == "Test Guitar Tuner Clip-On"

    def test_get_product_not_found(self, db_session):
        ops = DatabaseOperations()
        product = ops.get_product(db_session, "NONEXISTENT")
        assert product is None

    def test_get_product_suppliers(self, db_session, sample_product_supplier):
        ops = DatabaseOperations()
        suppliers = ops.get_product_suppliers(db_session, sample_product_supplier.asin)
        assert len(suppliers) == 1
        assert suppliers[0].is_preferred is True
