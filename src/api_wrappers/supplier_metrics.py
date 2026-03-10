"""
Supplier Metrics Module

Fetches and calculates supplier-related metrics for the dashboard.
"""

import logging
from typing import Dict, List, Any
from decimal import Decimal
from datetime import datetime

from src.database import SessionLocal, Supplier, ProductSupplier, Product
from sqlalchemy import func, desc

logger = logging.getLogger(__name__)


class SupplierMetrics:
    """
    Calculates supplier performance metrics for dashboard display.
    """

    def __init__(self):
        """Initialize the supplier metrics calculator."""
        self.session = SessionLocal()

    def get_all_suppliers(self) -> List[Dict[str, Any]]:
        """
        Get all active suppliers with their stats.

        Returns:
            List of supplier dictionaries
        """
        suppliers = self.session.query(Supplier).filter(
            Supplier.status == "active"
        ).all()

        supplier_data = []
        for supplier in suppliers:
            # Count products from this supplier
            product_count = self.session.query(ProductSupplier).filter(
                ProductSupplier.supplier_id == supplier.supplier_id
            ).count()

            # Calculate average metrics from product matches
            avg_metrics = self.session.query(
                func.avg(ProductSupplier.profit_margin).label('avg_margin'),
                func.avg(ProductSupplier.roi).label('avg_roi'),
                func.sum(ProductSupplier.estimated_profit).label('total_profit')
            ).filter(
                ProductSupplier.supplier_id == supplier.supplier_id
            ).first()

            supplier_data.append({
                'supplier_id': supplier.supplier_id,
                'name': supplier.name,
                'website': supplier.website,
                'contact_email': supplier.contact_email,
                'min_order_qty': supplier.min_order_qty,
                'lead_time_days': supplier.lead_time_days,
                'reliability_score': supplier.reliability_score,
                'on_time_delivery_rate': supplier.on_time_delivery_rate * 100,  # Convert to percentage
                'total_orders': supplier.total_orders,
                'product_count': product_count,
                'avg_profit_margin': float(avg_metrics.avg_margin or 0) * 100,  # Convert to percentage
                'avg_roi': float(avg_metrics.avg_roi or 0) * 100,  # Convert to percentage
                'total_potential_profit': float(avg_metrics.total_profit or 0),
                'status': supplier.status,
            })

        return supplier_data

    def get_product_supplier_matches(self, asin: str = None) -> List[Dict[str, Any]]:
        """
        Get product-supplier matches with detailed profitability.

        Args:
            asin: Optional ASIN to filter by

        Returns:
            List of product-supplier match dictionaries
        """
        query = self.session.query(
            ProductSupplier,
            Product,
            Supplier
        ).join(
            Product, ProductSupplier.asin == Product.asin
        ).join(
            Supplier, ProductSupplier.supplier_id == Supplier.supplier_id
        )

        if asin:
            query = query.filter(ProductSupplier.asin == asin)

        matches = query.order_by(
            desc(ProductSupplier.profit_margin)
        ).all()

        match_data = []
        for ps, product, supplier in matches:
            match_data.append({
                'asin': ps.asin,
                'product_title': product.title,
                'supplier_id': supplier.supplier_id,
                'supplier_name': supplier.name,
                'supplier_website': supplier.website,
                'amazon_price': float(product.current_price),
                'supplier_cost': float(ps.supplier_cost),
                'shipping_cost': float(ps.shipping_cost),
                'total_cost': float(ps.total_cost),
                'estimated_profit': float(ps.estimated_profit),
                'profit_margin': float(ps.profit_margin) * 100,  # Convert to percentage
                'roi': float(ps.roi) * 100,  # Convert to percentage
                'is_preferred': ps.is_preferred,
                'lead_time_days': supplier.lead_time_days,
                'min_order_qty': supplier.min_order_qty,
                'reliability_score': supplier.reliability_score,
            })

        return match_data

    def get_best_suppliers(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get the best suppliers ranked by average ROI.

        Args:
            limit: Number of top suppliers to return

        Returns:
            List of top supplier dictionaries
        """
        # Calculate average ROI per supplier
        supplier_stats = self.session.query(
            Supplier,
            func.avg(ProductSupplier.roi).label('avg_roi'),
            func.avg(ProductSupplier.profit_margin).label('avg_margin'),
            func.count(ProductSupplier.asin).label('product_count')
        ).join(
            ProductSupplier, Supplier.supplier_id == ProductSupplier.supplier_id
        ).group_by(
            Supplier.supplier_id
        ).order_by(
            desc('avg_roi')
        ).limit(limit).all()

        best_suppliers = []
        for supplier, avg_roi, avg_margin, product_count in supplier_stats:
            best_suppliers.append({
                'supplier_id': supplier.supplier_id,
                'name': supplier.name,
                'website': supplier.website,
                'avg_roi': float(avg_roi or 0) * 100,
                'avg_profit_margin': float(avg_margin or 0) * 100,
                'product_count': product_count,
                'reliability_score': supplier.reliability_score,
                'lead_time_days': supplier.lead_time_days,
            })

        return best_suppliers

    def get_supplier_summary(self) -> Dict[str, Any]:
        """
        Get overall supplier summary metrics.

        Returns:
            Dictionary with summary stats
        """
        total_suppliers = self.session.query(Supplier).filter(
            Supplier.status == "active"
        ).count()

        total_matches = self.session.query(ProductSupplier).count()

        avg_metrics = self.session.query(
            func.avg(ProductSupplier.profit_margin).label('avg_margin'),
            func.avg(ProductSupplier.roi).label('avg_roi')
        ).first()

        # Count preferred suppliers
        preferred_count = self.session.query(ProductSupplier).filter(
            ProductSupplier.is_preferred == True
        ).count()

        return {
            'total_suppliers': total_suppliers,
            'total_product_matches': total_matches,
            'avg_profit_margin': float(avg_metrics.avg_margin or 0) * 100,
            'avg_roi': float(avg_metrics.avg_roi or 0) * 100,
            'products_with_preferred_supplier': preferred_count,
        }

    def get_products_needing_suppliers(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get products that don't have supplier matches yet.

        Args:
            limit: Max products to return

        Returns:
            List of products without suppliers
        """
        # Get products without any supplier matches
        products_with_suppliers = self.session.query(
            ProductSupplier.asin
        ).distinct()

        products_without = self.session.query(Product).filter(
            Product.status == "active",
            Product.is_underserved == True,
            ~Product.asin.in_(products_with_suppliers)
        ).order_by(
            desc(Product.opportunity_score)
        ).limit(limit).all()

        product_data = []
        for product in products_without:
            product_data.append({
                'asin': product.asin,
                'title': product.title,
                'current_price': float(product.current_price),
                'opportunity_score': product.opportunity_score,
                'estimated_monthly_sales': product.estimated_monthly_sales,
            })

        return product_data

    def close(self):
        """Close the database session."""
        self.session.close()


# Singleton instance
_supplier_metrics_instance = None


def get_supplier_metrics() -> SupplierMetrics:
    """Get or create the SupplierMetrics instance."""
    global _supplier_metrics_instance
    if _supplier_metrics_instance is None:
        _supplier_metrics_instance = SupplierMetrics()
    return _supplier_metrics_instance
