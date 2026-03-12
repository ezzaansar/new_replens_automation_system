#!/usr/bin/env python3
"""
Production Automation Runner for Amazon FBA Replens System

Provides scheduled and manual execution of automation phases with
built-in alerting and reporting.

Usage:
  uv run python tools/run_automation.py daily              # Daily cycle (dry-run repricing)
  uv run python tools/run_automation.py daily --apply       # Daily cycle (live repricing)
  uv run python tools/run_automation.py weekly              # Weekly cycle
  uv run python tools/run_automation.py alerts              # Check and send alerts only
  uv run python tools/run_automation.py report              # Generate system health report

Cron examples:
  0 2 * * * cd /path/to/replens_new && uv run python tools/run_automation.py daily
  0 3 * * 0 cd /path/to/replens_new && uv run python tools/run_automation.py weekly
  0 * * * * cd /path/to/replens_new && uv run python tools/run_automation.py alerts
"""

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

# Add project root to sys.path so src imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config import settings
from src.database import (
    SessionLocal,
    Product,
    Supplier,
    ProductSupplier,
    Inventory,
    PurchaseOrder,
    Performance,
)
from src.phases import (
    phase_2_auto_discovery,
    phase_3_sourcing_google,
    phase_4_repricing,
    phase_5_forecasting,
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_file: str) -> logging.Logger:
    """Configure logging to both console and file."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger("automation_runner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# Alert delivery
# ---------------------------------------------------------------------------

def send_slack_alert(message: str, logger: logging.Logger) -> None:
    """Send an alert message to Slack if webhook URL is configured."""
    if not settings.slack_webhook_url:
        return
    try:
        import requests
        resp = requests.post(
            settings.slack_webhook_url,
            json={"text": message},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"Slack alert returned status {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Failed to send Slack alert: {exc}")


def deliver_alert(title: str, details: list[str], logger: logging.Logger) -> None:
    """Log an alert and optionally send it to Slack."""
    separator = "-" * 60
    logger.warning(separator)
    logger.warning(f"ALERT: {title}")
    for line in details:
        logger.warning(f"  {line}")
    logger.warning(separator)

    if settings.slack_webhook_url:
        slack_msg = f"*ALERT: {title}*\n" + "\n".join(f"  {d}" for d in details)
        send_slack_alert(slack_msg, logger)


# ---------------------------------------------------------------------------
# Phase runners (each wrapped with timing + error handling)
# ---------------------------------------------------------------------------

class PhaseResult:
    """Tracks the outcome of a single phase execution."""

    def __init__(self, name: str):
        self.name = name
        self.success: bool = False
        self.duration_s: float = 0.0
        self.error: str | None = None

    def __repr__(self):
        status = "OK" if self.success else f"FAILED ({self.error})"
        return f"{self.name}: {status} ({self.duration_s:.1f}s)"


def run_phase(name: str, func, logger: logging.Logger) -> PhaseResult:
    """Execute *func* inside a try/except, capturing timing and errors."""
    result = PhaseResult(name)
    logger.info(f"--- Starting: {name} ---")
    start = time.time()
    try:
        func()
        result.success = True
    except Exception as exc:
        result.error = str(exc)
        logger.error(f"{name} failed: {exc}")
        logger.debug(traceback.format_exc())
    result.duration_s = time.time() - start
    logger.info(f"--- Finished: {name} ({result.duration_s:.1f}s) ---")
    return result


# ---------------------------------------------------------------------------
# Alert checks (database queries)
# ---------------------------------------------------------------------------

def check_low_stock(session, logger: logging.Logger) -> list[str]:
    """Products where inventory.needs_reorder is True."""
    rows = (
        session.query(Product.asin, Product.title, Inventory.current_stock, Inventory.reorder_point)
        .join(Inventory, Inventory.asin == Product.asin)
        .filter(Inventory.needs_reorder == True)
        .all()
    )
    details = []
    for asin, title, stock, reorder_pt in rows:
        short_title = (title[:50] + "...") if title and len(title) > 50 else (title or "N/A")
        details.append(f"{asin} ({short_title}) — stock: {stock}, reorder point: {reorder_pt}")
    if details:
        deliver_alert(f"Low Stock: {len(details)} product(s) need reorder", details, logger)
    return details


def check_stale_data(session, logger: logging.Logger) -> list[str]:
    """Products not updated in more than 7 days."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = (
        session.query(Product.asin, Product.title, Product.last_updated)
        .filter(Product.status == "active")
        .filter((Product.last_updated < cutoff) | (Product.last_updated == None))
        .all()
    )
    details = []
    for asin, title, updated in rows:
        short_title = (title[:50] + "...") if title and len(title) > 50 else (title or "N/A")
        age = (datetime.utcnow() - updated).days if updated else "never"
        details.append(f"{asin} ({short_title}) — last updated: {age} days ago")
    if details:
        deliver_alert(f"Stale Data: {len(details)} product(s) not updated in >7 days", details, logger)
    return details


def check_unprofitable(session, logger: logging.Logger) -> list[str]:
    """Products with profit_potential < 0 that have real supplier costs."""
    rows = (
        session.query(Product.asin, Product.title, Product.profit_potential)
        .join(ProductSupplier, ProductSupplier.asin == Product.asin)
        .filter(Product.status == "active")
        .filter(Product.profit_potential < 0)
        .distinct()
        .all()
    )
    details = []
    for asin, title, profit in rows:
        short_title = (title[:50] + "...") if title and len(title) > 50 else (title or "N/A")
        details.append(f"{asin} ({short_title}) — profit potential: {profit}")
    if details:
        deliver_alert(f"Unprofitable: {len(details)} product(s) with negative profit", details, logger)
    return details


def check_overdue_pos(session, logger: logging.Logger) -> list[str]:
    """Purchase orders past expected delivery that are not received or cancelled."""
    now = datetime.utcnow()
    rows = (
        session.query(PurchaseOrder)
        .filter(PurchaseOrder.expected_delivery < now)
        .filter(~PurchaseOrder.status.in_(["received", "cancelled"]))
        .all()
    )
    details = []
    for po in rows:
        days_late = (now - po.expected_delivery).days if po.expected_delivery else 0
        details.append(
            f"PO {po.po_id} — ASIN {po.asin}, status: {po.status}, "
            f"{days_late} day(s) overdue"
        )
    if details:
        deliver_alert(f"Overdue POs: {len(details)} purchase order(s) past due", details, logger)
    return details


def check_price_drops(session, logger: logging.Logger) -> list[str]:
    """Products where current price dropped >10% from 90-day average."""
    rows = (
        session.query(Product.asin, Product.title, Product.current_price, Product.price_history_avg)
        .filter(Product.status == "active")
        .filter(Product.current_price != None)
        .filter(Product.price_history_avg != None)
        .filter(Product.price_history_avg > 0)
        .all()
    )
    details = []
    for asin, title, price, avg in rows:
        if price is None or avg is None:
            continue
        drop_pct = float((avg - price) / avg) * 100
        if drop_pct > 10:
            short_title = (title[:50] + "...") if title and len(title) > 50 else (title or "N/A")
            details.append(
                f"{asin} ({short_title}) — current: {price}, avg: {avg}, drop: {drop_pct:.1f}%"
            )
    if details:
        deliver_alert(f"Price Drops >10%: {len(details)} product(s)", details, logger)
    return details


def check_buy_box_lost(session, logger: logging.Logger) -> list[str]:
    """Products where latest performance shows buy_box_owned is False."""
    from sqlalchemy import func

    subq = (
        session.query(
            Performance.asin,
            func.max(Performance.date).label("max_date"),
        )
        .group_by(Performance.asin)
        .subquery()
    )
    rows = (
        session.query(Performance)
        .join(subq, (Performance.asin == subq.c.asin) & (Performance.date == subq.c.max_date))
        .filter(Performance.buy_box_owned == False)
        .all()
    )
    details = []
    for perf in rows:
        product = session.query(Product).filter(Product.asin == perf.asin).first()
        title = product.title if product else "N/A"
        short_title = (title[:50] + "...") if title and len(title) > 50 else title
        competitor = perf.competitor_price or "unknown"
        details.append(f"{perf.asin} ({short_title}) — competitor price: {competitor}")
    if details:
        deliver_alert(f"Buy Box Lost: {len(details)} product(s)", details, logger)
    return details


def run_all_alerts(logger: logging.Logger) -> dict:
    """Run every alert check and return a summary dict."""
    session = SessionLocal()
    try:
        results = {
            "low_stock": check_low_stock(session, logger),
            "stale_data": check_stale_data(session, logger),
            "unprofitable": check_unprofitable(session, logger),
            "overdue_pos": check_overdue_pos(session, logger),
            "price_drops": check_price_drops(session, logger),
            "buy_box_lost": check_buy_box_lost(session, logger),
        }
        total = sum(len(v) for v in results.values())
        if total == 0:
            logger.info("All alert checks passed — no issues found.")
        else:
            logger.warning(f"Total alert items: {total}")
        return results
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(logger: logging.Logger) -> str:
    """Generate a text summary of system health."""
    session = SessionLocal()
    try:
        now = datetime.utcnow()

        total_products = session.query(Product).filter(Product.status == "active").count()
        products_with_costs = (
            session.query(Product.asin)
            .join(ProductSupplier, ProductSupplier.asin == Product.asin)
            .filter(Product.status == "active")
            .distinct()
            .count()
        )
        profitable = (
            session.query(Product)
            .filter(Product.status == "active", Product.profit_potential > 0)
            .count()
        )
        unprofitable = (
            session.query(Product)
            .join(ProductSupplier, ProductSupplier.asin == Product.asin)
            .filter(Product.status == "active", Product.profit_potential < 0)
            .distinct()
            .count()
        )

        # Inventory
        needs_reorder = session.query(Inventory).filter(Inventory.needs_reorder == True).count()
        total_inventory = session.query(Inventory).count()
        total_units = session.query(
            __import__("sqlalchemy").func.coalesce(
                __import__("sqlalchemy").func.sum(Inventory.current_stock), 0
            )
        ).scalar()

        # Purchase orders
        pending_pos = (
            session.query(PurchaseOrder)
            .filter(PurchaseOrder.status.in_(["pending", "confirmed", "shipped"]))
            .count()
        )
        overdue_pos = (
            session.query(PurchaseOrder)
            .filter(PurchaseOrder.expected_delivery < now)
            .filter(~PurchaseOrder.status.in_(["received", "cancelled"]))
            .count()
        )

        # Suppliers
        active_suppliers = session.query(Supplier).filter(Supplier.status == "active").count()

        # Last update timestamps
        latest_product_update = (
            session.query(__import__("sqlalchemy").func.max(Product.last_updated)).scalar()
        )
        latest_inventory_update = (
            session.query(__import__("sqlalchemy").func.max(Inventory.last_updated)).scalar()
        )
        latest_perf = (
            session.query(__import__("sqlalchemy").func.max(Performance.date)).scalar()
        )

        def fmt_ts(ts):
            if ts is None:
                return "never"
            age = now - ts
            if age.days > 0:
                return f"{ts.strftime('%Y-%m-%d %H:%M')} ({age.days}d ago)"
            hours = age.seconds // 3600
            return f"{ts.strftime('%Y-%m-%d %H:%M')} ({hours}h ago)"

        lines = [
            "=" * 60,
            "  AMAZON FBA REPLENS — SYSTEM HEALTH REPORT",
            f"  Generated: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "=" * 60,
            "",
            "PRODUCTS",
            f"  Total active products:      {total_products}",
            f"  With real supplier costs:    {products_with_costs}",
            f"  Profitable (potential > 0):  {profitable}",
            f"  Unprofitable (with costs):   {unprofitable}",
            "",
            "INVENTORY",
            f"  Tracked SKUs:               {total_inventory}",
            f"  Total units in stock:        {total_units}",
            f"  Needing reorder:             {needs_reorder}",
            "",
            "PURCHASE ORDERS",
            f"  Pending / in-transit:        {pending_pos}",
            f"  Overdue:                     {overdue_pos}",
            "",
            "SUPPLIERS",
            f"  Active suppliers:            {active_suppliers}",
            "",
            "LAST RUN TIMESTAMPS",
            f"  Product data updated:        {fmt_ts(latest_product_update)}",
            f"  Inventory updated:           {fmt_ts(latest_inventory_update)}",
            f"  Performance recorded:        {fmt_ts(latest_perf)}",
            "",
            "=" * 60,
        ]
        report = "\n".join(lines)
        for line in lines:
            logger.info(line)
        return report
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_daily(args, logger: logging.Logger) -> None:
    """Run the daily automation cycle."""
    logger.info("========== DAILY AUTOMATION CYCLE ==========")
    results: list[PhaseResult] = []

    # Phase 2: Discovery
    results.append(run_phase(
        "Phase 2: Auto Discovery",
        lambda: phase_2_auto_discovery.AutoDiscoveryEngine().run_with_keywords(
            keywords=[
                "violin accessories",
                "guitar accessories",
                "music instrument care",
                "violin rosin",
                "instrument strings",
            ],
            max_products=50,
        ),
        logger,
    ))

    # Phase 4: Repricing
    apply = getattr(args, "apply", False)
    mode = "LIVE" if apply else "DRY-RUN"
    results.append(run_phase(
        f"Phase 4: Repricing ({mode})",
        lambda: phase_4_repricing.RepricingEngine(dry_run=not apply).run(),
        logger,
    ))

    # Phase 5: Forecasting
    results.append(run_phase(
        "Phase 5: Forecasting",
        lambda: phase_5_forecasting.ForecastingEngine().run(limit=50, auto_po=False),
        logger,
    ))

    # Alerts
    logger.info("--- Running daily alert checks ---")
    alert_results = run_all_alerts(logger)

    # Summary
    _print_summary(results, alert_results, logger)


def cmd_weekly(args, logger: logging.Logger) -> None:
    """Run the weekly automation cycle."""
    logger.info("========== WEEKLY AUTOMATION CYCLE ==========")
    results: list[PhaseResult] = []

    # Phase 2: Discovery with expanded keywords
    expanded_keywords = [
        "violin accessories",
        "guitar accessories",
        "music instrument care",
        "violin rosin",
        "instrument strings",
        "ukulele accessories",
        "piano accessories",
        "drum accessories",
        "music stands",
        "instrument cases",
        "sheet music accessories",
        "audio cables",
    ]
    results.append(run_phase(
        "Phase 2: Discovery (expanded)",
        lambda: phase_2_auto_discovery.AutoDiscoveryEngine().run_with_keywords(
            keywords=expanded_keywords,
            max_products=100,
        ),
        logger,
    ))

    # Phase 3: Supplier sourcing
    results.append(run_phase(
        "Phase 3: Supplier Sourcing",
        lambda: phase_3_sourcing_google.main(),
        logger,
    ))

    # Phase 5: Forecasting with auto-PO
    results.append(run_phase(
        "Phase 5: Forecasting (auto-PO)",
        lambda: phase_5_forecasting.ForecastingEngine().run(limit=50, auto_po=True),
        logger,
    ))

    # Generate summary report
    logger.info("--- Generating weekly summary report ---")
    generate_report(logger)

    # Summary
    _print_summary(results, {}, logger)


def cmd_alerts(args, logger: logging.Logger) -> None:
    """Check and send alerts only (no phase execution)."""
    logger.info("========== ALERT CHECK ==========")
    alert_results = run_all_alerts(logger)
    total = sum(len(v) for v in alert_results.values())
    logger.info(f"Alert check complete. Total issues: {total}")


def cmd_report(args, logger: logging.Logger) -> None:
    """Generate a system health report."""
    generate_report(logger)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_summary(
    phase_results: list[PhaseResult],
    alert_results: dict,
    logger: logging.Logger,
) -> None:
    """Print a final run summary."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  RUN SUMMARY")
    logger.info("=" * 60)

    succeeded = [r for r in phase_results if r.success]
    failed = [r for r in phase_results if not r.success]
    total_time = sum(r.duration_s for r in phase_results)

    logger.info(f"  Phases run:      {len(phase_results)}")
    logger.info(f"  Succeeded:       {len(succeeded)}")
    logger.info(f"  Failed:          {len(failed)}")
    logger.info(f"  Total time:      {total_time:.1f}s")
    logger.info("")

    for r in phase_results:
        status = "OK" if r.success else "FAILED"
        logger.info(f"  [{status:6s}] {r.name} ({r.duration_s:.1f}s)")
        if r.error:
            logger.info(f"           Error: {r.error}")

    if alert_results:
        total_alerts = sum(len(v) for v in alert_results.values())
        logger.info("")
        logger.info(f"  Alert items:     {total_alerts}")
        for category, items in alert_results.items():
            if items:
                logger.info(f"    {category}: {len(items)}")

    logger.info("=" * 60)

    if failed:
        # Send a Slack summary for failures
        fail_names = ", ".join(r.name for r in failed)
        send_slack_alert(
            f"Automation run completed with failures: {fail_names}",
            logger,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Amazon FBA Replens — Production Automation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python tools/run_automation.py daily\n"
            "  uv run python tools/run_automation.py daily --apply\n"
            "  uv run python tools/run_automation.py weekly\n"
            "  uv run python tools/run_automation.py alerts\n"
            "  uv run python tools/run_automation.py report\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # daily
    daily_parser = subparsers.add_parser("daily", help="Run daily automation cycle")
    daily_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply repricing changes (default: dry-run)",
    )

    # weekly
    subparsers.add_parser("weekly", help="Run weekly automation cycle")

    # alerts
    subparsers.add_parser("alerts", help="Check and send alerts only")

    # report
    subparsers.add_parser("report", help="Generate system health report")

    args = parser.parse_args()

    # Choose log file based on command
    log_files = {
        "daily": os.path.join(PROJECT_ROOT, "logs", "automation_daily.log"),
        "weekly": os.path.join(PROJECT_ROOT, "logs", "automation_weekly.log"),
        "alerts": os.path.join(PROJECT_ROOT, "logs", "automation_alerts.log"),
        "report": os.path.join(PROJECT_ROOT, "logs", "automation_report.log"),
    }
    log_file = log_files.get(args.command, os.path.join(PROJECT_ROOT, "logs", "automation.log"))
    logger = setup_logging(log_file)

    command_map = {
        "daily": cmd_daily,
        "weekly": cmd_weekly,
        "alerts": cmd_alerts,
        "report": cmd_report,
    }

    handler = command_map[args.command]
    logger.info(f"Automation runner started — command: {args.command}")
    start = time.time()

    try:
        handler(args, logger)
    except Exception as exc:
        logger.error(f"Unhandled error in '{args.command}': {exc}")
        logger.error(traceback.format_exc())
        send_slack_alert(f"Automation runner CRASHED during '{args.command}': {exc}", logger)
        sys.exit(1)

    elapsed = time.time() - start
    logger.info(f"Automation runner finished in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
