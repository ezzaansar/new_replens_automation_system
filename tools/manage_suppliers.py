"""
Supplier Cost Management Tool

Fills in real supplier costs to replace the 50% COGS estimates.
Supports:
  - Export CSV template for manual cost research
  - Import CSV with real supplier costs
  - Update individual product costs
  - Recalculate profitability & scores with real costs
  - View current supplier cost status

Usage:
  uv run python tools/manage_suppliers.py export           # Export CSV template
  uv run python tools/manage_suppliers.py import costs.csv  # Import costs from CSV
  uv run python tools/manage_suppliers.py update B0BF5W643L 3.50 0.80  # ASIN cost shipping
  uv run python tools/manage_suppliers.py recalculate       # Recalculate all profitability
  uv run python tools/manage_suppliers.py status            # Show cost coverage stats
"""

import argparse
import csv
import logging
import sys
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import (
    SessionLocal, Product, Supplier, ProductSupplier,
    DatabaseOperations, Performance
)
from src.config import (
    settings, AMAZON_REFERRAL_FEES, AMAZON_FBA_FEE_DEFAULT,
    CATEGORY_SALES_CURVES
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

CSV_DIR = project_root / "data"
DEFAULT_EXPORT_FILE = CSV_DIR / "supplier_costs_template.csv"
DEFAULT_IMPORT_FILE = CSV_DIR / "supplier_costs.csv"


def get_referral_fee_rate(category: str) -> float:
    """Get Amazon referral fee rate for a category."""
    cat_lower = (category or "").lower().strip()
    for key, rate in AMAZON_REFERRAL_FEES.items():
        if key in cat_lower:
            return rate
    return AMAZON_REFERRAL_FEES["default"]


def calculate_profitability(price: Decimal, supplier_cost: Decimal,
                            shipping_cost: Decimal, category: str) -> dict:
    """
    Calculate profitability metrics for a product with real costs.

    Returns dict with: total_cost, referral_fee, fba_fee, total_fees,
                       net_profit, profit_margin, roi
    """
    total_cost = supplier_cost + shipping_cost

    referral_rate = Decimal(str(get_referral_fee_rate(category)))
    referral_fee = price * referral_rate
    fba_fee = AMAZON_FBA_FEE_DEFAULT
    total_fees = referral_fee + fba_fee

    net_profit = price - total_cost - total_fees
    profit_margin = float(net_profit / price) if price > 0 else 0.0
    roi = float(net_profit / total_cost) if total_cost > 0 else 0.0

    return {
        "total_cost": total_cost,
        "referral_fee": referral_fee,
        "fba_fee": fba_fee,
        "total_fees": total_fees,
        "net_profit": net_profit,
        "profit_margin": profit_margin,
        "roi": roi,
    }


def export_template(limit: int = 50, output_file: str = None):
    """
    Export a CSV template with top products for manual cost research.

    Includes product details, supplier links, and empty cost columns to fill in.
    """
    output_path = Path(output_file) if output_file else DEFAULT_EXPORT_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    session = SessionLocal()
    try:
        # Get top underserved products ordered by score
        products = session.query(Product)\
            .filter(Product.is_underserved == True, Product.status == "active")\
            .order_by(Product.opportunity_score.desc())\
            .limit(limit)\
            .all()

        if not products:
            # Fall back to all active products
            products = session.query(Product)\
                .filter(Product.status == "active")\
                .order_by(Product.opportunity_score.desc())\
                .limit(limit)\
                .all()

        rows = []
        for product in products:
            # Get existing supplier links
            ps_links = session.query(ProductSupplier)\
                .filter(ProductSupplier.asin == product.asin)\
                .all()

            # Get supplier URLs
            supplier_urls = []
            supplier_id = None
            for ps in ps_links:
                supplier = session.query(Supplier)\
                    .filter(Supplier.supplier_id == ps.supplier_id)\
                    .first()
                if supplier:
                    supplier_urls.append(supplier.website or "")
                    if not supplier_id:
                        supplier_id = supplier.supplier_id

            existing_cost = None
            for ps in ps_links:
                if ps.supplier_cost and float(ps.supplier_cost) > 0:
                    existing_cost = float(ps.supplier_cost)
                    break

            rows.append({
                "asin": product.asin,
                "title": (product.title or "")[:80],
                "category": product.category or "",
                "amazon_price": f"{product.current_price:.2f}" if product.current_price else "0.00",
                "opportunity_score": f"{product.opportunity_score:.1f}",
                "estimated_monthly_sales": product.estimated_monthly_sales or 0,
                "num_sellers": product.num_sellers or 0,
                "supplier_cost": f"{existing_cost:.2f}" if existing_cost else "",
                "shipping_cost": "",
                "supplier_name": "",
                "supplier_url": "; ".join(supplier_urls[:3]) if supplier_urls else "",
                "moq": "",
                "lead_time_days": "",
                "notes": "",
            })

        # Write CSV
        fieldnames = [
            "asin", "title", "category", "amazon_price", "opportunity_score",
            "estimated_monthly_sales", "num_sellers",
            "supplier_cost", "shipping_cost", "supplier_name", "supplier_url",
            "moq", "lead_time_days", "notes"
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Exported {len(rows)} products to {output_path}")
        logger.info(f"")
        logger.info(f"NEXT STEPS:")
        logger.info(f"  1. Open {output_path} in Excel/Google Sheets")
        logger.info(f"  2. Research supplier costs on Alibaba, Global Sources, etc.")
        logger.info(f"  3. Fill in 'supplier_cost' and 'shipping_cost' columns (GBP)")
        logger.info(f"  4. Optionally fill supplier_name, moq, lead_time_days")
        logger.info(f"  5. Save as CSV and run:")
        logger.info(f"     uv run python tools/manage_suppliers.py import {output_path}")

    finally:
        session.close()


def import_costs(input_file: str = None):
    """
    Import supplier costs from a CSV file.

    Expected columns: asin, supplier_cost, shipping_cost
    Optional columns: supplier_name, supplier_url, moq, lead_time_days, notes
    """
    input_path = Path(input_file) if input_file else DEFAULT_IMPORT_FILE

    if not input_path.exists():
        logger.error(f"File not found: {input_path}")
        logger.info(f"Run 'export' first to create a template, then fill in costs.")
        return

    session = SessionLocal()
    try:
        updated = 0
        skipped = 0
        errors = 0
        new_suppliers = 0

        with open(input_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):
                asin = row.get("asin", "").strip()
                if not asin:
                    skipped += 1
                    continue

                # Parse costs
                cost_str = row.get("supplier_cost", "").strip()
                shipping_str = row.get("shipping_cost", "").strip()

                if not cost_str:
                    skipped += 1
                    continue

                try:
                    supplier_cost = Decimal(cost_str)
                    shipping_cost = Decimal(shipping_str) if shipping_str else Decimal("0")
                except InvalidOperation:
                    logger.warning(f"Row {row_num}: Invalid cost for {asin}: cost='{cost_str}', shipping='{shipping_str}'")
                    errors += 1
                    continue

                if supplier_cost <= 0:
                    logger.warning(f"Row {row_num}: Skipping {asin} - cost must be > 0")
                    skipped += 1
                    continue

                # Verify product exists
                product = session.query(Product).filter(Product.asin == asin).first()
                if not product:
                    logger.warning(f"Row {row_num}: ASIN {asin} not found in database")
                    errors += 1
                    continue

                # Create or find supplier
                supplier_name = row.get("supplier_name", "").strip()
                supplier_url = row.get("supplier_url", "").strip()
                moq_str = row.get("moq", "").strip()
                lead_time_str = row.get("lead_time_days", "").strip()
                notes = row.get("notes", "").strip()

                supplier = _find_or_create_supplier(
                    session, supplier_name, supplier_url,
                    moq_str, lead_time_str, notes
                )
                if supplier and not supplier.supplier_id:
                    new_suppliers += 1

                # Calculate profitability with real costs
                price = product.current_price or Decimal("0")
                profit = calculate_profitability(
                    price, supplier_cost, shipping_cost,
                    product.category or ""
                )

                # Update or create product-supplier link
                _update_product_supplier(
                    session, asin, supplier,
                    supplier_cost, shipping_cost, profit
                )

                # Update product profit_potential with real cost profit
                product.profit_potential = profit["net_profit"]
                product.last_updated = datetime.utcnow()

                session.commit()
                updated += 1

                status = "PROFITABLE" if profit["net_profit"] > 0 else "UNPROFITABLE"
                logger.info(
                    f"  {asin} | cost: £{supplier_cost:.2f} + £{shipping_cost:.2f} "
                    f"| profit: £{profit['net_profit']:.2f} "
                    f"| margin: {profit['profit_margin']:.0%} "
                    f"| roi: {profit['roi']:.0%} "
                    f"| {status}"
                )

        logger.info(f"")
        logger.info(f"IMPORT COMPLETE")
        logger.info(f"  Updated: {updated}")
        logger.info(f"  Skipped: {skipped} (empty cost)")
        logger.info(f"  Errors: {errors}")
        if new_suppliers:
            logger.info(f"  New suppliers created: {new_suppliers}")
        logger.info(f"")

        if updated > 0:
            logger.info(f"Run 'recalculate' to update opportunity scores:")
            logger.info(f"  uv run python tools/manage_suppliers.py recalculate")

    finally:
        session.close()


def _find_or_create_supplier(session, name: str, url: str,
                              moq_str: str, lead_time_str: str,
                              notes: str) -> Supplier:
    """Find existing supplier or create a new one."""
    # Try to find by URL first
    if url:
        # Handle multiple URLs separated by semicolons
        first_url = url.split(";")[0].strip()
        existing = session.query(Supplier).filter(
            Supplier.website == first_url
        ).first()
        if existing:
            return existing

    # Try to find by name
    if name:
        existing = session.query(Supplier).filter(
            Supplier.name == name
        ).first()
        if existing:
            return existing

    # Use first available supplier if no name/url given
    if not name and not url:
        first_supplier = session.query(Supplier).first()
        if first_supplier:
            return first_supplier

    # Create new supplier
    moq = int(moq_str) if moq_str and moq_str.isdigit() else 1
    lead_time = int(lead_time_str) if lead_time_str and lead_time_str.isdigit() else 7

    supplier = Supplier(
        name=name or f"Supplier-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        website=url.split(";")[0].strip() if url else None,
        min_order_qty=moq,
        lead_time_days=lead_time,
        reliability_score=50.0,  # Default until proven
        on_time_delivery_rate=0.0,
        status="active",
        notes=notes or "Added via CSV import"
    )
    session.add(supplier)
    session.flush()  # Get supplier_id
    return supplier


def _update_product_supplier(session, asin: str, supplier: Supplier,
                              supplier_cost: Decimal, shipping_cost: Decimal,
                              profit: dict):
    """Update or create a product-supplier link with real costs."""
    existing = session.query(ProductSupplier).filter(
        ProductSupplier.asin == asin,
        ProductSupplier.supplier_id == supplier.supplier_id
    ).first()

    total_cost = supplier_cost + shipping_cost

    if existing:
        existing.supplier_cost = supplier_cost
        existing.shipping_cost = shipping_cost
        existing.total_cost = total_cost
        existing.estimated_profit = profit["net_profit"]
        existing.profit_margin = profit["profit_margin"]
        existing.roi = profit["roi"]
        existing.is_preferred = profit["net_profit"] > 0
        existing.last_updated = datetime.utcnow()
    else:
        ps = ProductSupplier(
            asin=asin,
            supplier_id=supplier.supplier_id,
            supplier_cost=supplier_cost,
            shipping_cost=shipping_cost,
            total_cost=total_cost,
            estimated_profit=profit["net_profit"],
            profit_margin=profit["profit_margin"],
            roi=profit["roi"],
            is_preferred=profit["net_profit"] > 0,
            status="active"
        )
        session.add(ps)


def update_single(asin: str, cost: str, shipping: str = "0"):
    """Update supplier cost for a single ASIN."""
    session = SessionLocal()
    try:
        product = session.query(Product).filter(Product.asin == asin).first()
        if not product:
            logger.error(f"ASIN {asin} not found in database")
            return

        try:
            supplier_cost = Decimal(cost)
            shipping_cost = Decimal(shipping)
        except InvalidOperation:
            logger.error(f"Invalid cost values: cost='{cost}', shipping='{shipping}'")
            return

        if supplier_cost <= 0:
            logger.error("Supplier cost must be > 0")
            return

        price = product.current_price or Decimal("0")
        profit = calculate_profitability(
            price, supplier_cost, shipping_cost,
            product.category or ""
        )

        # Get or create supplier link
        supplier = session.query(Supplier).first()
        if not supplier:
            supplier = Supplier(
                name="Manual Entry",
                status="active",
                notes="Created for manual cost entry"
            )
            session.add(supplier)
            session.flush()

        _update_product_supplier(
            session, asin, supplier,
            supplier_cost, shipping_cost, profit
        )

        product.profit_potential = profit["net_profit"]
        product.last_updated = datetime.utcnow()

        session.commit()

        logger.info(f"Updated {asin}: {product.title[:60]}")
        logger.info(f"  Amazon price:   £{price:.2f}")
        logger.info(f"  Supplier cost:  £{supplier_cost:.2f}")
        logger.info(f"  Shipping:       £{shipping_cost:.2f}")
        logger.info(f"  Total cost:     £{supplier_cost + shipping_cost:.2f}")
        logger.info(f"  Referral fee:   £{profit['referral_fee']:.2f}")
        logger.info(f"  FBA fee:        £{profit['fba_fee']:.2f}")
        logger.info(f"  Net profit:     £{profit['net_profit']:.2f}")
        logger.info(f"  Margin:         {profit['profit_margin']:.1%}")
        logger.info(f"  ROI:            {profit['roi']:.1%}")

        status = "PROFITABLE" if profit["net_profit"] > 0 else "UNPROFITABLE"
        logger.info(f"  Status:         {status}")

    finally:
        session.close()


def recalculate_all():
    """
    Recalculate profitability and opportunity scores for all products
    that have real supplier costs.
    """
    session = SessionLocal()
    try:
        # Get all products with real supplier costs
        products_with_costs = session.query(Product).join(
            ProductSupplier, Product.asin == ProductSupplier.asin
        ).filter(
            ProductSupplier.supplier_cost > 0
        ).all()

        if not products_with_costs:
            logger.info("No products have real supplier costs yet.")
            logger.info("Run 'export' to create a template, fill in costs, then 'import'.")
            return

        updated = 0
        profitable = 0
        unprofitable = 0

        for product in products_with_costs:
            # Get best (lowest) supplier cost
            best_ps = session.query(ProductSupplier)\
                .filter(
                    ProductSupplier.asin == product.asin,
                    ProductSupplier.supplier_cost > 0
                )\
                .order_by(ProductSupplier.supplier_cost.asc())\
                .first()

            if not best_ps:
                continue

            price = product.current_price or Decimal("0")
            supplier_cost = best_ps.supplier_cost or Decimal("0")
            shipping_cost = best_ps.shipping_cost or Decimal("0")

            profit = calculate_profitability(
                price, supplier_cost, shipping_cost,
                product.category or ""
            )

            # Update product-supplier link
            best_ps.estimated_profit = profit["net_profit"]
            best_ps.profit_margin = profit["profit_margin"]
            best_ps.roi = profit["roi"]
            best_ps.total_cost = profit["total_cost"]
            best_ps.is_preferred = True
            best_ps.last_updated = datetime.utcnow()

            # Recalculate opportunity score
            new_score = _recalculate_score(product, profit)

            product.profit_potential = profit["net_profit"]
            product.opportunity_score = new_score
            product.is_underserved = new_score >= 60
            product.last_updated = datetime.utcnow()

            if profit["net_profit"] > 0:
                profitable += 1
            else:
                unprofitable += 1

            updated += 1

        session.commit()

        logger.info(f"RECALCULATION COMPLETE")
        logger.info(f"  Products updated:  {updated}")
        logger.info(f"  Profitable:        {profitable}")
        logger.info(f"  Unprofitable:      {unprofitable}")
        logger.info(f"")

        # Show top profitable products
        top = session.query(Product).join(
            ProductSupplier, Product.asin == ProductSupplier.asin
        ).filter(
            ProductSupplier.supplier_cost > 0,
            Product.profit_potential > 0
        ).order_by(Product.opportunity_score.desc()).limit(10).all()

        if top:
            logger.info(f"TOP 10 PROFITABLE PRODUCTS (with real costs):")
            logger.info(f"{'ASIN':<12} {'Score':>6} {'Price':>7} {'Profit':>8} {'Title'}")
            logger.info(f"{'-'*12} {'-'*6} {'-'*7} {'-'*8} {'-'*40}")
            for p in top:
                logger.info(
                    f"{p.asin:<12} {p.opportunity_score:>5.1f} "
                    f"£{p.current_price:>5.2f} £{p.profit_potential:>6.2f} "
                    f"{(p.title or '')[:40]}"
                )

    finally:
        session.close()


def _recalculate_score(product: Product, profit: dict) -> float:
    """
    Recalculate opportunity score using real profitability data.

    Uses same weights as DiscoveryModel but with real cost data.
    """
    from src.models.discovery_model import DiscoveryModel
    model = DiscoveryModel()

    # Price stability
    price_stability = float(product.price_stability or 0.5)

    # Competition
    num_sellers = product.num_sellers or 10
    num_sellers_low = 1.0 if num_sellers < 5 else 0.0

    # Sales rank
    sales_rank = product.sales_rank or 100000
    sales_rank_good = 1.0 if sales_rank < 50000 else 0.0

    # Sales velocity (normalized)
    monthly_sales = product.estimated_monthly_sales or 0
    sales_velocity = min(monthly_sales / 100.0, 1.0)

    # Real profitability
    profit_margin = min(max(profit["profit_margin"], 0), 1.0)
    roi = min(max(profit["roi"] / 10.0, 0), 1.0)

    feature_vector = [
        price_stability,
        num_sellers_low,
        sales_rank_good,
        sales_velocity,
        profit_margin,
        roi,
    ]

    score = model.predict(feature_vector)

    # Apply business rules
    if profit["profit_margin"] < settings.min_profit_margin:
        score *= 0.5
    if profit["roi"] < settings.min_roi:
        score *= 0.5
    if monthly_sales < settings.min_sales_velocity:
        score *= 0.5

    return max(0, min(100, score * 100))


def show_status():
    """Show current supplier cost coverage status."""
    session = SessionLocal()
    try:
        total_products = session.query(Product).filter(Product.status == "active").count()
        underserved = session.query(Product).filter(
            Product.is_underserved == True, Product.status == "active"
        ).count()

        total_links = session.query(ProductSupplier).count()
        with_costs = session.query(ProductSupplier).filter(
            ProductSupplier.supplier_cost > 0
        ).count()
        zero_costs = total_links - with_costs

        # Products that have at least one real cost
        products_with_real_costs = session.query(Product.asin).join(
            ProductSupplier, Product.asin == ProductSupplier.asin
        ).filter(ProductSupplier.supplier_cost > 0).distinct().count()

        # Profitable products (real costs, positive profit)
        profitable = session.query(Product).join(
            ProductSupplier, Product.asin == ProductSupplier.asin
        ).filter(
            ProductSupplier.supplier_cost > 0,
            Product.profit_potential > 0
        ).count()

        total_suppliers = session.query(Supplier).count()

        coverage_pct = (products_with_real_costs / total_products * 100) if total_products > 0 else 0

        logger.info(f"SUPPLIER COST STATUS")
        logger.info(f"{'='*50}")
        logger.info(f"  Total active products:     {total_products}")
        logger.info(f"  Underserved (score >= 60): {underserved}")
        logger.info(f"  Total suppliers:           {total_suppliers}")
        logger.info(f"  Total product-supplier links: {total_links}")
        logger.info(f"")
        logger.info(f"  COST COVERAGE:")
        logger.info(f"    With real costs:    {with_costs} links ({products_with_real_costs} products)")
        logger.info(f"    Missing costs:      {zero_costs} links")
        logger.info(f"    Coverage:           {coverage_pct:.1f}%")
        logger.info(f"")
        logger.info(f"  PROFITABILITY (real costs only):")
        logger.info(f"    Profitable:         {profitable}")
        logger.info(f"    Unprofitable:       {products_with_real_costs - profitable}")
        logger.info(f"")

        if products_with_real_costs == 0:
            logger.info(f"  No real costs yet! Get started:")
            logger.info(f"    1. uv run python tools/manage_suppliers.py export")
            logger.info(f"    2. Fill in costs in data/supplier_costs_template.csv")
            logger.info(f"    3. uv run python tools/manage_suppliers.py import data/supplier_costs_template.csv")
        elif coverage_pct < 50:
            logger.info(f"  Coverage is low. Export more products to research:")
            logger.info(f"    uv run python tools/manage_suppliers.py export --limit 50")
        else:
            logger.info(f"  Good coverage! Run recalculate to update scores:")
            logger.info(f"    uv run python tools/manage_suppliers.py recalculate")

        # Show products needing costs (top 10 by score)
        logger.info(f"")
        logger.info(f"TOP PRODUCTS NEEDING REAL COSTS:")
        logger.info(f"{'ASIN':<12} {'Score':>6} {'Price':>7} {'Sales/mo':>9} {'Title'}")
        logger.info(f"{'-'*12} {'-'*6} {'-'*7} {'-'*9} {'-'*40}")

        # Products without real costs, sorted by score
        from sqlalchemy import and_
        asins_with_costs = session.query(ProductSupplier.asin).filter(
            ProductSupplier.supplier_cost > 0
        ).distinct().subquery()

        products_without = session.query(Product)\
            .filter(
                Product.is_underserved == True,
                Product.status == "active",
                ~Product.asin.in_(session.query(asins_with_costs.c.asin))
            )\
            .order_by(Product.opportunity_score.desc())\
            .limit(10)\
            .all()

        for p in products_without:
            logger.info(
                f"  {p.asin:<12} {p.opportunity_score:>5.1f} "
                f"£{p.current_price or 0:>5.2f} "
                f"{p.estimated_monthly_sales or 0:>8} "
                f"{(p.title or '')[:40]}"
            )

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Supplier Cost Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                          # Show cost coverage
  %(prog)s export                          # Export CSV template (top 50)
  %(prog)s export --limit 20              # Export top 20 only
  %(prog)s export --output my_costs.csv   # Custom output file
  %(prog)s import data/supplier_costs_template.csv  # Import filled CSV
  %(prog)s update B0BF5W643L 3.50 0.80    # Update single ASIN
  %(prog)s recalculate                     # Recalculate scores with real costs
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export CSV template")
    export_parser.add_argument("--limit", type=int, default=50,
                               help="Number of products to export (default: 50)")
    export_parser.add_argument("--output", "-o", type=str, default=None,
                               help="Output CSV file path")

    # Import command
    import_parser = subparsers.add_parser("import", help="Import costs from CSV")
    import_parser.add_argument("file", type=str, nargs="?", default=None,
                               help="CSV file to import")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update single ASIN cost")
    update_parser.add_argument("asin", type=str, help="Product ASIN")
    update_parser.add_argument("cost", type=str, help="Supplier cost (GBP)")
    update_parser.add_argument("shipping", type=str, nargs="?", default="0",
                               help="Shipping cost (GBP, default: 0)")

    # Recalculate command
    subparsers.add_parser("recalculate", help="Recalculate profitability & scores")

    # Status command
    subparsers.add_parser("status", help="Show cost coverage status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "export":
        export_template(limit=args.limit, output_file=args.output)
    elif args.command == "import":
        import_costs(input_file=args.file)
    elif args.command == "update":
        update_single(args.asin, args.cost, args.shipping)
    elif args.command == "recalculate":
        recalculate_all()
    elif args.command == "status":
        show_status()


if __name__ == "__main__":
    main()
