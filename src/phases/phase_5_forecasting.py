"""
Phase 5: Inventory Forecasting & Replenishment

Predicts future demand and automates inventory replenishment:
1. Fetches current inventory levels from Amazon SP-API
2. Calculates average daily sales from order history and Performance table
3. Forecasts future stock levels using exponential smoothing
4. Computes reorder points and safety stock
5. Flags products that need reordering
6. Generates purchase orders for low-stock products
"""

import logging
import sys
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from decimal import Decimal

import numpy as np

from src.database import (
    SessionLocal, Product, ProductSupplier, Supplier,
    Inventory, PurchaseOrder, Performance, DatabaseOperations,
)
from src.api_wrappers.amazon_sp_api import get_sp_api
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


class ForecastingEngine:
    """
    Inventory forecasting and replenishment engine.

    Uses exponential smoothing on historical sales data to predict demand,
    then calculates reorder points and generates purchase orders.
    """

    def __init__(self):
        self.session = SessionLocal()
        self.db = DatabaseOperations()
        self.sp_api = get_sp_api()

        # Config
        self.forecast_days = settings.forecast_days_ahead
        self.safety_stock_days = settings.safety_stock_days
        self.reorder_multiplier = settings.reorder_point_multiplier
        self.seasonality = settings.seasonality_adjustment
        self.promotion_factor = settings.promotion_impact_factor

        logger.info("Forecasting engine initialized")

    # ------------------------------------------------------------------
    # 1. Fetch current FBA inventory from Amazon
    # ------------------------------------------------------------------

    def sync_inventory(self) -> Dict[str, Dict[str, int]]:
        """
        Pull live FBA inventory from SP-API and upsert into the Inventory table.

        Returns:
            Mapping of ASIN -> {current_stock, reserved, available}
        """
        logger.info("Syncing inventory from Amazon SP-API...")

        try:
            summaries = self.sp_api.get_inventory_summaries()
        except Exception as e:
            logger.warning(f"Could not fetch live inventory: {e}")
            summaries = []

        inventory_map: Dict[str, Dict[str, int]] = {}

        for item in summaries:
            asin = item.get("asin")
            if not asin:
                continue

            total = int(item.get("totalQuantity", 0))
            reserved = int(item.get("reservedQuantity", 0))
            available = int(item.get("fulfillableQuantity", 0))

            # Aggregate if same ASIN appears multiple times (different SKUs)
            if asin in inventory_map:
                inventory_map[asin]["current_stock"] += total
                inventory_map[asin]["reserved"] += reserved
                inventory_map[asin]["available"] += available
            else:
                inventory_map[asin] = {
                    "current_stock": total,
                    "reserved": reserved,
                    "available": available,
                }

        # Upsert aggregated inventory records
        for asin, counts in inventory_map.items():
            inv = self.session.query(Inventory).filter(Inventory.asin == asin).first()
            if not inv:
                inv = Inventory(asin=asin)
                self.session.add(inv)

            inv.current_stock = counts["current_stock"]
            inv.reserved = counts["reserved"]
            inv.available = counts["available"]
            inv.last_updated = datetime.utcnow()

        self.session.commit()
        logger.info(f"Synced inventory for {len(inventory_map)} SKUs")
        return inventory_map

    # ------------------------------------------------------------------
    # 2. Build daily sales history
    # ------------------------------------------------------------------

    def fetch_orders_once(self, days: int = 90) -> Dict[str, List[float]]:
        """
        Fetch orders from SP-API once and aggregate daily sales per ASIN.

        Returns:
            Mapping of ASIN -> list of daily sales values.
        """
        if hasattr(self, "_orders_cache"):
            return self._orders_cache

        start = datetime.utcnow() - timedelta(days=days)
        asin_daily: Dict[str, Dict[str, int]] = {}

        try:
            orders = self.sp_api.get_orders(created_after=start)
            for order in orders:
                date_str = order.get("PurchaseDate", "")[:10]
                try:
                    items = self.sp_api.get_order_items(order["AmazonOrderId"])
                except Exception:
                    continue
                for it in items:
                    asin = it.get("ASIN")
                    if not asin:
                        continue
                    qty = int(it.get("QuantityOrdered", 0))
                    if asin not in asin_daily:
                        asin_daily[asin] = {}
                    asin_daily[asin][date_str] = asin_daily[asin].get(date_str, 0) + qty
        except Exception as e:
            logger.debug(f"Could not fetch orders from SP-API: {e}")

        # Convert to sorted daily sales lists
        self._orders_cache: Dict[str, List[float]] = {}
        for asin, daily in asin_daily.items():
            sorted_days = sorted(daily.keys())
            self._orders_cache[asin] = [float(daily[d]) for d in sorted_days]

        return self._orders_cache

    def get_daily_sales(self, asin: str, days: int = 90) -> List[float]:
        """
        Return a list of daily unit sales for the last *days* days.

        First tries the Performance table; falls back to pre-fetched SP-API
        orders cache. If neither source has data, estimates from the product's
        estimated_monthly_sales field.
        """
        start = datetime.utcnow() - timedelta(days=days)

        # --- Source 1: Performance table ---
        rows = (
            self.session.query(Performance)
            .filter(Performance.asin == asin, Performance.date >= start)
            .order_by(Performance.date)
            .all()
        )

        if rows:
            return [float(r.units_sold) for r in rows]

        # --- Source 2: Pre-fetched SP-API orders ---
        orders_cache = self.fetch_orders_once(days)
        if asin in orders_cache and orders_cache[asin]:
            return orders_cache[asin]

        # --- Source 3: estimated_monthly_sales from Product table ---
        product = self.db.get_product(self.session, asin)
        if product and product.estimated_monthly_sales:
            daily_est = product.estimated_monthly_sales / 30.0
            return [daily_est] * min(days, 30)

        return []

    # ------------------------------------------------------------------
    # 3. Exponential smoothing forecast
    # ------------------------------------------------------------------

    @staticmethod
    def exponential_smoothing(series: List[float], alpha: float = 0.3) -> List[float]:
        """
        Simple exponential smoothing.

        Args:
            series: historical daily values
            alpha:  smoothing factor (0 < alpha <= 1)

        Returns:
            Smoothed series of same length.
        """
        if not series:
            return []
        result = [series[0]]
        for val in series[1:]:
            result.append(alpha * val + (1 - alpha) * result[-1])
        return result

    def forecast_demand(self, daily_sales: List[float], days_ahead: int) -> float:
        """
        Forecast total units demanded over the next *days_ahead* days.

        Uses exponential smoothing to derive a smoothed daily rate,
        then extrapolates.
        """
        if not daily_sales:
            return 0.0

        smoothed = self.exponential_smoothing(daily_sales)
        avg_daily = smoothed[-1] if smoothed else 0.0

        # Apply seasonality bump if enabled and we have enough history
        if self.seasonality and len(daily_sales) >= 60:
            recent_avg = np.mean(daily_sales[-30:])
            older_avg = np.mean(daily_sales[-60:-30]) or 1.0
            seasonal_ratio = recent_avg / older_avg if older_avg > 0 else 1.0
            # Clamp to avoid extreme multipliers
            seasonal_ratio = max(0.5, min(2.0, seasonal_ratio))
            avg_daily *= seasonal_ratio

        return avg_daily * days_ahead

    # ------------------------------------------------------------------
    # 4. Reorder calculations
    # ------------------------------------------------------------------

    def compute_reorder_params(
        self,
        avg_daily_sales: float,
        lead_time_days: int,
    ) -> Dict[str, float]:
        """
        Calculate safety stock and reorder point.

        safety_stock  = avg_daily_sales * safety_stock_days
        reorder_point = avg_daily_sales * lead_time_days * reorder_multiplier
                        + safety_stock
        """
        safety_stock = avg_daily_sales * self.safety_stock_days
        lead_time_demand = avg_daily_sales * lead_time_days
        reorder_point = lead_time_demand * self.reorder_multiplier + safety_stock

        return {
            "safety_stock": round(safety_stock),
            "reorder_point": round(reorder_point),
            "lead_time_demand": round(lead_time_demand),
        }

    # ------------------------------------------------------------------
    # 5. Process a single product
    # ------------------------------------------------------------------

    def process_product(self, product: Product) -> Dict[str, Any]:
        """Run forecasting for one product and update its Inventory record."""

        asin = product.asin
        result: Dict[str, Any] = {
            "asin": asin,
            "title": product.title,
            "action": "none",
        }

        # --- daily sales ---
        daily_sales = self.get_daily_sales(asin, days=90)
        if not daily_sales:
            logger.info(f"  No sales data for {asin} — skipping")
            result["action"] = "skipped_no_data"
            return result

        smoothed = self.exponential_smoothing(daily_sales)
        avg_daily = smoothed[-1] if smoothed else 0.0
        result["avg_daily_sales"] = round(avg_daily, 2)

        # --- forecast ---
        demand_30d = self.forecast_demand(daily_sales, 30)
        demand_60d = self.forecast_demand(daily_sales, 60)
        result["demand_30d"] = round(demand_30d)
        result["demand_60d"] = round(demand_60d)

        # --- inventory record ---
        inv = self.session.query(Inventory).filter(Inventory.asin == asin).first()
        if not inv:
            inv = Inventory(asin=asin, current_stock=0, reserved=0, available=0)
            self.session.add(inv)

        current_stock = inv.current_stock or 0

        # --- inbound stock from pending POs ---
        pending_pos = (
            self.session.query(PurchaseOrder)
            .filter(
                PurchaseOrder.asin == asin,
                PurchaseOrder.status.in_(["pending", "confirmed", "shipped"]),
            )
            .all()
        )
        inbound_qty = sum(po.quantity for po in pending_pos)
        effective_stock = current_stock + inbound_qty

        # --- projected stock ---
        projected_30d = max(0, round(effective_stock - demand_30d))
        projected_60d = max(0, round(effective_stock - demand_60d))

        # --- supplier lead time ---
        best_supplier = (
            self.session.query(ProductSupplier)
            .filter(ProductSupplier.asin == asin)
            .order_by(ProductSupplier.profit_margin.desc())
            .first()
        )
        if best_supplier:
            supplier = (
                self.session.query(Supplier)
                .filter(Supplier.supplier_id == best_supplier.supplier_id)
                .first()
            )
            lead_time = supplier.lead_time_days if supplier and supplier.lead_time_days else 14
        else:
            lead_time = 14  # default assumption

        # --- reorder params ---
        params = self.compute_reorder_params(avg_daily, lead_time)

        # --- days of supply ---
        days_of_supply = current_stock / avg_daily if avg_daily > 0 else 999

        # --- update inventory ---
        inv.forecasted_stock_30d = projected_30d
        inv.forecasted_stock_60d = projected_60d
        inv.reorder_point = params["reorder_point"]
        inv.safety_stock = params["safety_stock"]
        inv.days_of_supply = round(days_of_supply, 1)
        inv.needs_reorder = current_stock <= params["reorder_point"]
        inv.last_updated = datetime.utcnow()

        result["current_stock"] = current_stock
        result["inbound"] = inbound_qty
        result["projected_30d"] = projected_30d
        result["projected_60d"] = projected_60d
        result["days_of_supply"] = round(days_of_supply, 1)
        result["reorder_point"] = params["reorder_point"]
        result["safety_stock"] = params["safety_stock"]
        result["needs_reorder"] = inv.needs_reorder

        if inv.needs_reorder:
            result["action"] = "reorder_needed"
        else:
            result["action"] = "ok"

        return result

    # ------------------------------------------------------------------
    # 6. Auto-generate purchase orders
    # ------------------------------------------------------------------

    def generate_purchase_order(self, asin: str, avg_daily_sales: float) -> Optional[PurchaseOrder]:
        """
        Create a PurchaseOrder for a product that needs restocking.

        Order quantity = enough to cover forecast_days_ahead + safety_stock,
        rounded up to the supplier's min_order_qty.
        """
        best_match = (
            self.session.query(ProductSupplier)
            .filter(ProductSupplier.asin == asin)
            .order_by(ProductSupplier.profit_margin.desc())
            .first()
        )
        if not best_match:
            logger.info(f"  No supplier for {asin} — cannot create PO")
            return None

        supplier = (
            self.session.query(Supplier)
            .filter(Supplier.supplier_id == best_match.supplier_id)
            .first()
        )
        if not supplier:
            return None

        # target quantity
        target = avg_daily_sales * self.forecast_days + (avg_daily_sales * self.safety_stock_days)
        target = max(target, 1)

        # round up to min_order_qty
        moq = max(supplier.min_order_qty or 1, 1)
        order_qty = int(np.ceil(target / moq) * moq)

        unit_cost = best_match.supplier_cost or Decimal("0")
        total_cost = Decimal(str(order_qty)) * unit_cost

        lead_time = supplier.lead_time_days if supplier.lead_time_days else 14
        expected_delivery = datetime.utcnow() + timedelta(days=lead_time)

        po = PurchaseOrder(
            po_id=f"PO-{uuid.uuid4().hex[:8].upper()}",
            asin=asin,
            supplier_id=supplier.supplier_id,
            quantity=order_qty,
            unit_cost=unit_cost,
            total_cost=total_cost,
            status="pending",
            expected_delivery=expected_delivery,
            notes=f"Auto-generated by Phase 5 forecasting. ADS={avg_daily_sales:.1f}",
        )
        self.session.add(po)
        logger.info(
            f"  PO created: {po.po_id} — {order_qty} units from {supplier.name[:40]}, "
            f"ETA {expected_delivery.strftime('%Y-%m-%d')}"
        )
        return po

    # ------------------------------------------------------------------
    # 7. Main run
    # ------------------------------------------------------------------

    def run(self, limit: int = 50, auto_po: bool = False) -> Dict[str, Any]:
        """
        Run the forecasting engine on all active products.

        Args:
            limit:   max products to process
            auto_po: if True, auto-create purchase orders for low-stock items
        """
        logger.info("=" * 60)
        logger.info("PHASE 5: INVENTORY FORECASTING & REPLENISHMENT")
        logger.info("=" * 60)
        logger.info(f"Forecast window:  {self.forecast_days} days")
        logger.info(f"Safety stock:     {self.safety_stock_days} days")
        logger.info(f"Reorder mult:     {self.reorder_multiplier}x")
        logger.info(f"Auto PO creation: {auto_po}")

        # 1. Sync live inventory
        self.sync_inventory()

        # 2. Get active products
        products = (
            self.session.query(Product)
            .filter(Product.status == "active")
            .limit(limit)
            .all()
        )
        logger.info(f"\nProcessing {len(products)} active products")

        stats = {
            "products_processed": 0,
            "forecasts_updated": 0,
            "reorders_needed": 0,
            "purchase_orders_created": 0,
            "skipped": 0,
        }

        reorder_list: List[Dict[str, Any]] = []

        for i, product in enumerate(products):
            logger.info(f"\n{'='*60}")
            logger.info(f"[{i+1}/{len(products)}] {product.title[:70]}")
            logger.info(f"  ASIN: {product.asin}")

            result = self.process_product(product)
            stats["products_processed"] += 1

            if result["action"] == "skipped_no_data":
                stats["skipped"] += 1
                continue

            stats["forecasts_updated"] += 1

            logger.info(
                f"  ADS={result['avg_daily_sales']}  "
                f"Stock={result['current_stock']}+{result['inbound']} inbound  "
                f"DoS={result['days_of_supply']}d  "
                f"30d→{result['projected_30d']}  60d→{result['projected_60d']}"
            )

            if result["needs_reorder"]:
                stats["reorders_needed"] += 1
                reorder_list.append(result)
                logger.info(f"  ⚠ REORDER NEEDED (stock {result['current_stock']} <= RP {result['reorder_point']})")

                if auto_po:
                    po = self.generate_purchase_order(
                        product.asin,
                        result["avg_daily_sales"],
                    )
                    if po:
                        stats["purchase_orders_created"] += 1

        self.session.commit()

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("PHASE 5 COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Products processed:     {stats['products_processed']}")
        logger.info(f"Forecasts updated:      {stats['forecasts_updated']}")
        logger.info(f"Skipped (no data):      {stats['skipped']}")
        logger.info(f"Reorders needed:        {stats['reorders_needed']}")
        logger.info(f"Purchase orders created: {stats['purchase_orders_created']}")

        if reorder_list:
            logger.info(f"\nProducts needing reorder:")
            for r in reorder_list:
                logger.info(
                    f"  {r['asin']}  stock={r['current_stock']}  "
                    f"RP={r['reorder_point']}  DoS={r['days_of_supply']}d  "
                    f"— {r['title'][:50]}"
                )

        logger.info(f"{'='*60}")
        return stats


def main():
    """Run Phase 5 inventory forecasting."""
    import argparse

    parser = argparse.ArgumentParser(description="Inventory Forecasting & Replenishment")
    parser.add_argument("--max", type=int, default=50, help="Max products to process")
    parser.add_argument(
        "--auto-po",
        action="store_true",
        help="Auto-create purchase orders for low-stock items",
    )
    args = parser.parse_args()

    try:
        engine = ForecastingEngine()
        stats = engine.run(limit=args.max, auto_po=args.auto_po)

        if stats["reorders_needed"] > 0:
            logger.info(f"\n⚠ {stats['reorders_needed']} product(s) need reordering")
            if not args.auto_po:
                logger.info("  Re-run with --auto-po to generate purchase orders automatically")
        else:
            logger.info("\n✓ All products are adequately stocked")

        return True

    except Exception as e:
        logger.error(f"Phase 5 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
