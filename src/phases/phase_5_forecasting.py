"""
Phase 5: Inventory Forecasting & Replenishment

Predicts future demand and automates inventory replenishment:
1. Fetches current inventory levels from Amazon SP-API
2. Builds daily sales estimates from Keepa sales rank history
3. Forecasts demand using multiple methods (SES, Holt's, WMA)
4. Selects best method via holdout validation
5. Computes reorder points, safety stock, and confidence intervals
6. Flags products needing reordering
7. Generates purchase orders for low-stock products

Usage:
  uv run python -m src.phases.phase_5_forecasting              # Run forecasting
  uv run python -m src.phases.phase_5_forecasting --auto-po     # Auto-create POs
  uv run python -m src.phases.phase_5_forecasting --max 20      # Limit products
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal

import numpy as np
import pandas as pd

from src.database import (
    SessionLocal, Product, ProductSupplier, Supplier,
    Inventory, PurchaseOrder, Performance, DatabaseOperations,
)
from src.api_wrappers.amazon_sp_api import get_sp_api
from src.api_wrappers.keepa_api import get_keepa_api
from src.config import settings, CATEGORY_SALES_CURVES

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


# ======================================================================
# Forecasting Methods
# ======================================================================

def simple_exponential_smoothing(series: np.ndarray, alpha: float = 0.3) -> np.ndarray:
    """
    Simple Exponential Smoothing (SES).

    Good for data without trend or seasonality.
    level(t) = alpha * y(t) + (1 - alpha) * level(t-1)
    """
    if len(series) == 0:
        return np.array([])
    result = np.zeros(len(series))
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result


def holts_double_exponential(
    series: np.ndarray, alpha: float = 0.3, beta: float = 0.1
) -> Tuple[np.ndarray, float, float]:
    """
    Holt's Double Exponential Smoothing.

    Captures both level and trend. Better for data with upward/downward drift.

    Returns:
        (smoothed_series, final_level, final_trend)
    """
    if len(series) < 2:
        return series.copy(), float(series[0]) if len(series) else 0.0, 0.0

    level = np.zeros(len(series))
    trend = np.zeros(len(series))

    # Initialize
    level[0] = series[0]
    trend[0] = series[1] - series[0]

    for i in range(1, len(series)):
        level[i] = alpha * series[i] + (1 - alpha) * (level[i - 1] + trend[i - 1])
        trend[i] = beta * (level[i] - level[i - 1]) + (1 - beta) * trend[i - 1]

    smoothed = level + trend
    return smoothed, float(level[-1]), float(trend[-1])


def weighted_moving_average(series: np.ndarray, window: int = 7) -> np.ndarray:
    """
    Weighted Moving Average — recent values get higher weight.

    Weights increase linearly: [1, 2, 3, ..., window].
    """
    if len(series) < window:
        window = max(len(series), 1)

    weights = np.arange(1, window + 1, dtype=float)
    weights /= weights.sum()

    result = np.zeros(len(series))
    for i in range(len(series)):
        start = max(0, i - window + 1)
        segment = series[start: i + 1]
        w = weights[-len(segment):]
        w = w / w.sum()  # re-normalize for short segments
        result[i] = np.dot(segment, w)

    return result


def forecast_with_method(
    daily_sales: np.ndarray,
    days_ahead: int,
    method: str = "ses",
) -> Tuple[float, float]:
    """
    Forecast total demand over days_ahead using specified method.

    Returns:
        (forecasted_total_demand, avg_daily_rate)
    """
    if len(daily_sales) == 0:
        return 0.0, 0.0

    if method == "ses":
        smoothed = simple_exponential_smoothing(daily_sales, alpha=0.3)
        avg_daily = smoothed[-1]

    elif method == "holts":
        _, final_level, final_trend = holts_double_exponential(
            daily_sales, alpha=0.3, beta=0.1
        )
        # Project forward: level + trend * step for each future day
        # Total = sum over days_ahead of (level + trend * i)
        projected_daily = [final_level + final_trend * i for i in range(1, days_ahead + 1)]
        projected_daily = [max(0, d) for d in projected_daily]
        total = sum(projected_daily)
        avg_daily = total / days_ahead if days_ahead > 0 else 0
        return max(0, total), max(0, avg_daily)

    elif method == "wma":
        smoothed = weighted_moving_average(daily_sales, window=14)
        avg_daily = smoothed[-1]

    else:
        avg_daily = float(np.mean(daily_sales[-30:])) if len(daily_sales) >= 30 else float(np.mean(daily_sales))

    avg_daily = max(0, avg_daily)
    return avg_daily * days_ahead, avg_daily


def select_best_method(daily_sales: np.ndarray) -> str:
    """
    Select the best forecasting method using holdout validation.

    Splits data into train (80%) / test (20%), runs each method,
    returns the one with lowest MAE.
    """
    if len(daily_sales) < 14:
        return "ses"  # Not enough data to validate

    split = max(int(len(daily_sales) * 0.8), 7)
    train = daily_sales[:split]
    test = daily_sales[split:]
    test_days = len(test)

    if test_days == 0:
        return "ses"

    actual_total = float(np.sum(test))

    methods = {}
    for method in ["ses", "holts", "wma"]:
        predicted_total, _ = forecast_with_method(train, test_days, method)
        mae = abs(predicted_total - actual_total)
        methods[method] = mae

    best = min(methods, key=methods.get)
    logger.debug(f"  Method selection: {methods} -> {best}")
    return best


def compute_forecast_confidence(daily_sales: np.ndarray, days_ahead: int) -> Dict[str, float]:
    """
    Compute confidence intervals for the forecast.

    Uses the standard deviation of recent daily sales to estimate
    uncertainty at 80% and 95% confidence levels.
    """
    if len(daily_sales) < 7:
        return {"ci_80_low": 0, "ci_80_high": 0, "ci_95_low": 0, "ci_95_high": 0, "std_daily": 0}

    recent = daily_sales[-30:] if len(daily_sales) >= 30 else daily_sales
    std_daily = float(np.std(recent))
    mean_daily = float(np.mean(recent))

    # For total over days_ahead, std scales by sqrt(days)
    std_total = std_daily * np.sqrt(days_ahead)
    mean_total = mean_daily * days_ahead

    return {
        "ci_80_low": max(0, mean_total - 1.28 * std_total),
        "ci_80_high": mean_total + 1.28 * std_total,
        "ci_95_low": max(0, mean_total - 1.96 * std_total),
        "ci_95_high": mean_total + 1.96 * std_total,
        "std_daily": std_daily,
    }


# ======================================================================
# Keepa Sales Rank -> Daily Sales Conversion
# ======================================================================

def rank_to_daily_sales(rank: float, category: str) -> float:
    """
    Convert a sales rank to estimated daily sales using category-specific curves.

    Uses the same power-law curves as Phase 2 discovery.
    """
    if rank <= 0:
        return 0.0
    curve = CATEGORY_SALES_CURVES.get(category, CATEGORY_SALES_CURVES["default"])
    multiplier, exponent = curve
    monthly = max(0.1, multiplier * (rank ** exponent))
    return monthly / 30.0


def build_daily_sales_from_keepa(
    sales_time: np.ndarray, sales_rank: np.ndarray, category: str
) -> np.ndarray:
    """
    Build a daily sales time series from Keepa sales rank history.

    Converts irregular sales rank snapshots to regular daily estimates
    by forward-filling rank values and applying the category sales curve.

    Args:
        sales_time: Array of datetime objects from Keepa SALES_time
        sales_rank: Array of sales rank values from Keepa SALES
        category: Product category for sales curve lookup

    Returns:
        Array of daily sales estimates, one per day for the available range
    """
    if sales_time is None or len(sales_time) == 0:
        return np.array([])

    # Filter valid entries
    valid_mask = ~np.isnan(sales_rank) & (sales_rank > 0)
    if not np.any(valid_mask):
        return np.array([])

    times = sales_time[valid_mask]
    ranks = sales_rank[valid_mask]

    # Create a date-indexed series and resample to daily
    df = pd.DataFrame({"rank": ranks.astype(float)}, index=pd.DatetimeIndex(times))
    df = df[~df.index.duplicated(keep="last")]
    df = df.resample("D").last().ffill()

    if df.empty:
        return np.array([])

    # Convert each daily rank to sales estimate
    daily_sales = df["rank"].apply(lambda r: rank_to_daily_sales(r, category)).values

    return daily_sales


# ======================================================================
# Forecasting Engine
# ======================================================================

class ForecastingEngine:
    """
    Inventory forecasting and replenishment engine.

    Uses multiple forecasting methods on Keepa-derived sales data,
    selects the best via holdout validation, and computes reorder parameters.
    """

    def __init__(self):
        self.session = SessionLocal()
        self.db = DatabaseOperations()
        self.sp_api = get_sp_api()
        self.keepa = get_keepa_api()

        # Config
        self.forecast_days = settings.forecast_days_ahead
        self.safety_stock_days = settings.safety_stock_days
        self.reorder_multiplier = settings.reorder_point_multiplier
        self.seasonality = settings.seasonality_adjustment

        logger.info("Forecasting engine initialized")

    # ------------------------------------------------------------------
    # 1. Sync FBA inventory from Amazon
    # ------------------------------------------------------------------

    def sync_inventory(self) -> Dict[str, Dict[str, int]]:
        """Pull live FBA inventory from SP-API and upsert into the Inventory table."""
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
    # 2. Build daily sales history from multiple sources
    # ------------------------------------------------------------------

    def _fetch_orders_once(self, days: int = 90) -> Dict[str, List[float]]:
        """Fetch SP-API orders once and cache. Returns ASIN -> daily sales list."""
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

        self._orders_cache: Dict[str, List[float]] = {}
        for asin, daily in asin_daily.items():
            sorted_days = sorted(daily.keys())
            self._orders_cache[asin] = [float(daily[d]) for d in sorted_days]

        return self._orders_cache

    def get_daily_sales(self, product: Product, days: int = 90) -> Tuple[np.ndarray, str]:
        """
        Build daily sales time series for a product.

        Priority:
        1. Keepa sales rank history (best — uses real historical rank data)
        2. SP-API order history (actual sales)
        3. Performance table (recorded snapshots)
        4. estimated_monthly_sales flat estimate (fallback)

        Returns:
            (daily_sales_array, source_name)
        """
        asin = product.asin
        category = product.category or ""

        # --- Source 1: Keepa sales rank history ---
        try:
            keepa_data = self.keepa.get_product_data([asin])
            if keepa_data:
                data = keepa_data[0].get("data", {})
                sales_time = data.get("SALES_time")
                sales_rank = data.get("SALES")

                if sales_time is not None and len(sales_time) > 10:
                    daily = build_daily_sales_from_keepa(sales_time, sales_rank, category)
                    if len(daily) >= 14:
                        # Take last N days
                        daily = daily[-days:]
                        return daily, "keepa"
        except Exception as e:
            logger.debug(f"  Keepa fetch failed for {asin}: {e}")

        # --- Source 2: SP-API orders ---
        orders_cache = self._fetch_orders_once(days)
        if asin in orders_cache and len(orders_cache[asin]) >= 7:
            return np.array(orders_cache[asin]), "orders"

        # --- Source 3: Performance table ---
        start = datetime.utcnow() - timedelta(days=days)
        rows = (
            self.session.query(Performance)
            .filter(Performance.asin == asin, Performance.date >= start)
            .order_by(Performance.date)
            .all()
        )
        if rows and len(rows) >= 7:
            return np.array([float(r.units_sold) for r in rows]), "performance"

        # --- Source 4: Flat estimate from estimated_monthly_sales ---
        if product.estimated_monthly_sales and product.estimated_monthly_sales > 0:
            daily_est = product.estimated_monthly_sales / 30.0
            return np.array([daily_est] * min(days, 30)), "estimate"

        return np.array([]), "none"

    # ------------------------------------------------------------------
    # 3. Reorder calculations
    # ------------------------------------------------------------------

    def compute_reorder_params(
        self,
        avg_daily_sales: float,
        std_daily: float,
        lead_time_days: int,
    ) -> Dict[str, int]:
        """
        Calculate safety stock and reorder point.

        safety_stock  = Z * std_daily * sqrt(lead_time)  (Z=1.65 for 95% service)
                        + avg_daily * safety_stock_days
        reorder_point = avg_daily * lead_time * multiplier + safety_stock
        """
        # Statistical safety stock (demand variability during lead time)
        z_score = 1.65  # 95% service level
        variability_buffer = z_score * std_daily * np.sqrt(lead_time_days)

        # Time-based safety stock
        time_buffer = avg_daily_sales * self.safety_stock_days

        safety_stock = variability_buffer + time_buffer

        lead_time_demand = avg_daily_sales * lead_time_days
        reorder_point = lead_time_demand * self.reorder_multiplier + safety_stock

        return {
            "safety_stock": max(0, round(safety_stock)),
            "reorder_point": max(0, round(reorder_point)),
            "lead_time_demand": max(0, round(lead_time_demand)),
        }

    # ------------------------------------------------------------------
    # 4. Process a single product
    # ------------------------------------------------------------------

    def process_product(self, product: Product) -> Dict[str, Any]:
        """Run forecasting for one product and update its Inventory record."""
        asin = product.asin
        result: Dict[str, Any] = {
            "asin": asin,
            "title": (product.title or "")[:50],
            "action": "none",
        }

        # --- Get daily sales ---
        daily_sales, source = self.get_daily_sales(product, days=90)
        if len(daily_sales) == 0:
            logger.info(f"  No sales data — skipping")
            result["action"] = "skipped_no_data"
            return result

        result["data_source"] = source
        result["data_points"] = len(daily_sales)

        # --- Select best forecast method ---
        best_method = select_best_method(daily_sales)
        result["forecast_method"] = best_method

        # --- Forecast demand ---
        demand_30d, avg_daily = forecast_with_method(daily_sales, 30, best_method)
        demand_60d, _ = forecast_with_method(daily_sales, 60, best_method)
        result["avg_daily_sales"] = round(avg_daily, 2)
        result["demand_30d"] = round(demand_30d)
        result["demand_60d"] = round(demand_60d)

        # --- Confidence intervals ---
        ci = compute_forecast_confidence(daily_sales, 30)
        result["ci_80"] = f"{ci['ci_80_low']:.0f}-{ci['ci_80_high']:.0f}"
        result["ci_95"] = f"{ci['ci_95_low']:.0f}-{ci['ci_95_high']:.0f}"
        result["std_daily"] = round(ci["std_daily"], 2)

        # --- Seasonality adjustment ---
        if self.seasonality and len(daily_sales) >= 60:
            recent_avg = float(np.mean(daily_sales[-30:]))
            older_avg = float(np.mean(daily_sales[-60:-30]))
            if older_avg > 0:
                seasonal_ratio = recent_avg / older_avg
                seasonal_ratio = max(0.5, min(2.0, seasonal_ratio))
                if abs(seasonal_ratio - 1.0) > 0.1:
                    demand_30d *= seasonal_ratio
                    demand_60d *= seasonal_ratio
                    avg_daily *= seasonal_ratio
                    result["seasonality_factor"] = round(seasonal_ratio, 2)
                    result["demand_30d"] = round(demand_30d)
                    result["demand_60d"] = round(demand_60d)
                    result["avg_daily_sales"] = round(avg_daily, 2)

        # --- Inventory record ---
        inv = self.session.query(Inventory).filter(Inventory.asin == asin).first()
        if not inv:
            inv = Inventory(asin=asin, current_stock=0, reserved=0, available=0)
            self.session.add(inv)

        current_stock = inv.current_stock or 0

        # --- Inbound stock from pending POs ---
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

        # --- Projected stock ---
        projected_30d = max(0, round(effective_stock - demand_30d))
        projected_60d = max(0, round(effective_stock - demand_60d))

        # --- Supplier lead time ---
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
            lead_time = (supplier.lead_time_days if supplier and supplier.lead_time_days else 14)
        else:
            lead_time = 14

        # --- Reorder params (with uncertainty) ---
        params = self.compute_reorder_params(avg_daily, ci["std_daily"], lead_time)

        # --- Days of supply ---
        days_of_supply = current_stock / avg_daily if avg_daily > 0 else 999

        # --- Update inventory record ---
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
        result["lead_time"] = lead_time
        result["needs_reorder"] = inv.needs_reorder

        if inv.needs_reorder:
            result["action"] = "reorder_needed"
        else:
            result["action"] = "ok"

        return result

    # ------------------------------------------------------------------
    # 5. Auto-generate purchase orders
    # ------------------------------------------------------------------

    def generate_purchase_order(
        self, asin: str, avg_daily_sales: float
    ) -> Optional[PurchaseOrder]:
        """
        Create a PurchaseOrder for a product that needs restocking.

        Order quantity covers forecast_days + safety stock, rounded to MOQ.
        """
        best_match = (
            self.session.query(ProductSupplier)
            .filter(ProductSupplier.asin == asin, ProductSupplier.supplier_cost > 0)
            .order_by(ProductSupplier.profit_margin.desc())
            .first()
        )
        if not best_match:
            logger.info(f"  No supplier with real costs for {asin} — cannot create PO")
            return None

        supplier = (
            self.session.query(Supplier)
            .filter(Supplier.supplier_id == best_match.supplier_id)
            .first()
        )
        if not supplier:
            return None

        target = avg_daily_sales * self.forecast_days + (avg_daily_sales * self.safety_stock_days)
        target = max(target, 1)

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
            notes=f"Auto-generated. ADS={avg_daily_sales:.1f}, method=best-fit",
        )
        self.session.add(po)
        logger.info(
            f"  PO: {po.po_id} | {order_qty} units | £{total_cost:.2f} | "
            f"from {supplier.name[:30]} | ETA {expected_delivery.strftime('%Y-%m-%d')}"
        )
        return po

    # ------------------------------------------------------------------
    # 6. Main run
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
        logger.info(f"  Forecast window:  {self.forecast_days} days")
        logger.info(f"  Safety stock:     {self.safety_stock_days} days")
        logger.info(f"  Reorder mult:     {self.reorder_multiplier}x")
        logger.info(f"  Seasonality:      {self.seasonality}")
        logger.info(f"  Auto PO:          {auto_po}")

        # 1. Sync live inventory
        self.sync_inventory()

        # 2. Get active products (prioritize underserved)
        products = (
            self.session.query(Product)
            .filter(Product.status == "active")
            .order_by(Product.opportunity_score.desc())
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
            "methods_used": {"ses": 0, "holts": 0, "wma": 0},
            "data_sources": {"keepa": 0, "orders": 0, "performance": 0, "estimate": 0},
        }

        reorder_list: List[Dict[str, Any]] = []
        all_results: List[Dict[str, Any]] = []

        for i, product in enumerate(products):
            logger.info(f"\n[{i+1}/{len(products)}] {product.asin} | {(product.title or '')[:50]}")

            result = self.process_product(product)
            stats["products_processed"] += 1
            all_results.append(result)

            if result["action"] == "skipped_no_data":
                stats["skipped"] += 1
                continue

            stats["forecasts_updated"] += 1

            # Track method and source usage
            method = result.get("forecast_method", "ses")
            if method in stats["methods_used"]:
                stats["methods_used"][method] += 1
            source = result.get("data_source", "estimate")
            if source in stats["data_sources"]:
                stats["data_sources"][source] += 1

            logger.info(
                f"  ADS={result['avg_daily_sales']} | "
                f"30d={result['demand_30d']} ({result.get('ci_80', '?')}) | "
                f"Stock={result['current_stock']}+{result['inbound']} | "
                f"DoS={result['days_of_supply']}d | "
                f"method={method} src={result.get('data_source', '?')}"
            )

            if result["needs_reorder"]:
                stats["reorders_needed"] += 1
                reorder_list.append(result)
                logger.info(
                    f"  REORDER: stock {result['current_stock']} <= RP {result['reorder_point']}"
                )

                if auto_po:
                    po = self.generate_purchase_order(
                        product.asin, result["avg_daily_sales"]
                    )
                    if po:
                        stats["purchase_orders_created"] += 1

        self.session.commit()

        # --- Summary ---
        logger.info(f"\n{'='*60}")
        logger.info("PHASE 5 COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"  Products processed:     {stats['products_processed']}")
        logger.info(f"  Forecasts updated:      {stats['forecasts_updated']}")
        logger.info(f"  Skipped (no data):      {stats['skipped']}")
        logger.info(f"  Reorders needed:        {stats['reorders_needed']}")
        logger.info(f"  Purchase orders created: {stats['purchase_orders_created']}")
        logger.info(f"")
        logger.info(f"  Forecast methods: {stats['methods_used']}")
        logger.info(f"  Data sources:     {stats['data_sources']}")

        if reorder_list:
            logger.info(f"\n  PRODUCTS NEEDING REORDER:")
            logger.info(f"  {'ASIN':<12} {'Stock':>6} {'RP':>6} {'DoS':>6} {'ADS':>6} {'Title'}")
            logger.info(f"  {'-'*12} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*30}")
            for r in reorder_list:
                logger.info(
                    f"  {r['asin']:<12} {r['current_stock']:>5} "
                    f"{r['reorder_point']:>5} {r['days_of_supply']:>5.0f}d "
                    f"{r['avg_daily_sales']:>5.1f} {r['title'][:30]}"
                )

        # Summary table of all forecasted products
        forecasted = [r for r in all_results if r["action"] != "skipped_no_data"]
        if forecasted:
            logger.info(f"\n  FORECAST SUMMARY (top 15):")
            logger.info(
                f"  {'ASIN':<12} {'ADS':>6} {'30d':>6} {'CI-80%':>14} "
                f"{'Method':<6} {'Src':<8} {'Status'}"
            )
            logger.info(
                f"  {'-'*12} {'-'*6} {'-'*6} {'-'*14} "
                f"{'-'*6} {'-'*8} {'-'*10}"
            )
            for r in forecasted[:15]:
                status = "REORDER" if r.get("needs_reorder") else "OK"
                logger.info(
                    f"  {r['asin']:<12} {r['avg_daily_sales']:>5.1f} "
                    f"{r['demand_30d']:>5} {r.get('ci_80', 'N/A'):>14} "
                    f"{r.get('forecast_method', '?'):<6} "
                    f"{r.get('data_source', '?'):<8} {status}"
                )

        logger.info(f"{'='*60}")
        return stats


def main():
    """Run Phase 5 inventory forecasting."""
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
            logger.info(f"\n{stats['reorders_needed']} product(s) need reordering")
            if not args.auto_po:
                logger.info("  Re-run with --auto-po to generate purchase orders")
        else:
            logger.info("\nAll products are adequately stocked")

        return True

    except Exception as e:
        logger.error(f"Phase 5 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
