"""
Seller Metrics Module

Fetches and calculates seller-related metrics from Amazon SP-API.
Handles FBA inventory and orders.
"""

import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from decimal import Decimal

from src.api_wrappers.amazon_sp_api import get_sp_api

logger = logging.getLogger(__name__)


class SellerMetrics:
    """
    Fetches seller performance metrics from Amazon SP-API.

    Handles:
    - FBA Inventory
    - Orders
    - Sales data
    - Performance metrics
    """

    def __init__(self):
        """Initialize the seller metrics fetcher."""
        self.amazon_api = get_sp_api()
        logger.info("✓ SellerMetrics initialized")

    def get_inventory_summary(self) -> Dict[str, Any]:
        """
        Get FBA inventory summary.

        Returns:
            Dictionary with inventory summary
        """
        try:
            inventory_items = self.amazon_api.get_inventory_summaries()

            if not inventory_items:
                logger.warning("No inventory items returned from API")
                return {
                    'total_products': 0,
                    'total_units': 0,
                    'fba_units': 0,
                    'inventory_items': []
                }

            # Calculate totals
            total_units = 0
            fba_units = 0
            inventory_data = []

            for item in inventory_items:
                fulfillable_qty = item.get('fulfillableQuantity', 0)
                total_qty = item.get('totalQuantity', 0)

                # Use total quantity if available, otherwise fulfillable
                qty = total_qty if total_qty > 0 else fulfillable_qty
                total_units += qty
                fba_units += qty

                # Format for dashboard
                inventory_data.append({
                    'SKU': item.get('sellerSku', 'N/A'),
                    'ASIN': item.get('asin', 'N/A'),
                    'Product': item.get('productName', 'N/A')[:50],
                    'Channel': 'FBA',
                    'Available': fulfillable_qty,
                    'Total': total_qty,
                    'Inbound': item.get('inboundWorkingQuantity', 0),
                    'Reserved': item.get('reservedQuantity', 0),
                })

            logger.info(f"✓ Inventory summary: {len(inventory_items)} SKUs, {total_units} FBA units")

            return {
                'total_products': len(inventory_items),
                'total_units': total_units,
                'fba_units': fba_units,
                'inventory_items': inventory_data,
                'inventory_turnover': 0.0,  # Calculate separately if needed
            }

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"✗ Error fetching inventory summary: {e}")
            logger.error(f"Full traceback:\n{error_details}")
            return {
                'total_products': 0,
                'total_units': 0,
                'fba_units': 0,
                'inventory_items': [],
                'error': str(e),
                'error_details': error_details
            }

    def get_recent_orders(self, days: int = 7) -> Dict[str, Any]:
        """
        Get recent orders from Amazon SP-API.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with orders summary
        """
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            # Fetch orders
            orders = self.amazon_api.get_orders(
                created_after=start_date,
                order_statuses=['Shipped', 'Unshipped']
            )

            if not orders:
                logger.info(f"No orders found in the last {days} days")
                return {
                    'total_orders': 0,
                    'total_revenue': 0.0,
                    'total_items': 0,
                    'avg_order_value': 0.0,
                    'orders': []
                }

            # Calculate metrics
            total_revenue = 0.0
            total_items = 0
            orders_data = []

            for order in orders:
                order_total = float(order.get('OrderTotal', {}).get('Amount', 0))
                total_revenue += order_total

                # Get order items to count quantity
                order_items = self.amazon_api.get_order_items(order.get('AmazonOrderId'))
                num_items = len(order_items) if order_items else 0
                total_items += num_items

                # Format for dashboard
                orders_data.append({
                    'Order ID': order.get('AmazonOrderId', 'N/A'),
                    'Date': order.get('PurchaseDate', 'N/A')[:10],
                    'Status': order.get('OrderStatus', 'N/A'),
                    'Items': num_items,
                    'Total': f"£{order_total:.2f}",
                    'Channel': order.get('FulfillmentChannel', 'N/A'),
                })

            avg_order_value = total_revenue / len(orders) if orders else 0.0

            logger.info(f"✓ Orders summary: {len(orders)} orders, "
                       f"£{total_revenue:.2f} revenue in {days} days")

            return {
                'total_orders': len(orders),
                'total_revenue': total_revenue,
                'total_items': total_items,
                'avg_order_value': avg_order_value,
                'orders': orders_data[:100],  # Limit to 100 for display
            }

        except Exception as e:
            logger.error(f"✗ Error fetching orders: {e}")
            return {
                'total_orders': 0,
                'total_revenue': 0.0,
                'total_items': 0,
                'avg_order_value': 0.0,
                'orders': [],
                'error': str(e)
            }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get seller performance metrics.

        Returns:
            Dictionary with performance data
        """
        try:
            # Get orders for last 30 days
            orders_30d = self.get_recent_orders(days=30)
            orders_7d = self.get_recent_orders(days=7)

            # Calculate performance metrics
            revenue_30d = orders_30d.get('total_revenue', 0)
            revenue_7d = orders_7d.get('total_revenue', 0)

            # Extrapolate monthly from weekly if needed
            estimated_monthly_revenue = revenue_7d * 4.3 if revenue_7d > 0 else revenue_30d

            # Calculate order fulfillment rate (simplified)
            # In production, would use actual performance metrics API
            fulfillment_rate = 0.95  # Assume 95% default

            return {
                'revenue_30d': revenue_30d,
                'revenue_7d': revenue_7d,
                'estimated_monthly_revenue': estimated_monthly_revenue,
                'orders_30d': orders_30d.get('total_orders', 0),
                'orders_7d': orders_7d.get('total_orders', 0),
                'avg_order_value': orders_30d.get('avg_order_value', 0),
                'fulfillment_rate': fulfillment_rate,
            }

        except Exception as e:
            logger.error(f"✗ Error calculating performance metrics: {e}")
            return {
                'revenue_30d': 0,
                'revenue_7d': 0,
                'estimated_monthly_revenue': 0,
                'orders_30d': 0,
                'orders_7d': 0,
                'avg_order_value': 0,
                'fulfillment_rate': 0,
            }


# Singleton instance
_seller_metrics_instance = None


def get_seller_metrics() -> SellerMetrics:
    """Get or create the SellerMetrics instance."""
    global _seller_metrics_instance
    if _seller_metrics_instance is None:
        _seller_metrics_instance = SellerMetrics()
    return _seller_metrics_instance
