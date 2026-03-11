"""
Data Validation Script

Validates the reliability of data in the replens_automation database by:
1. Cross-checking stored product data against live Keepa API data
2. Auditing the profit calculation methodology
3. Validating the sales estimation formula
4. Checking supplier data quality
5. Testing discovery across multiple categories
6. Generating a comprehensive validation report

Usage:
    uv run python tools/validate_data.py                  # Full validation (uses live APIs)
    uv run python tools/validate_data.py --offline         # Offline-only checks (no API calls)
    uv run python tools/validate_data.py --sample 5        # Validate N products (default: 10)
"""

import sqlite3
import sys
import os
import argparse
import json
from datetime import datetime
from decimal import Decimal
from collections import Counter
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

DB_PATH = "replens_automation.db"


# =============================================================================
# HELPERS
# =============================================================================

class ValidationReport:
    """Collects and formats validation results."""

    def __init__(self):
        self.checks = []
        self.warnings = []
        self.failures = []
        self.stats = {}

    def add_check(self, name: str, passed: bool, detail: str = ""):
        status = "PASS" if passed else "FAIL"
        entry = {"name": name, "status": status, "detail": detail}
        self.checks.append(entry)
        if not passed:
            self.failures.append(entry)

    def add_warning(self, message: str):
        self.warnings.append(message)

    def set_stat(self, key: str, value):
        self.stats[key] = value

    def print_report(self):
        print("\n" + "=" * 80)
        print("DATA VALIDATION REPORT")
        print(f"Generated: {datetime.utcnow().isoformat()}")
        print("=" * 80)

        # Stats
        print("\n--- DATABASE OVERVIEW ---")
        for key, val in self.stats.items():
            print(f"  {key}: {val}")

        # Checks
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        total = len(self.checks)
        print(f"\n--- CHECKS: {passed}/{total} PASSED ---")
        for c in self.checks:
            icon = "OK" if c["status"] == "PASS" else "XX"
            print(f"  [{icon}] {c['name']}")
            if c["detail"]:
                for line in c["detail"].split("\n"):
                    print(f"       {line}")

        # Warnings
        if self.warnings:
            print(f"\n--- WARNINGS ({len(self.warnings)}) ---")
            for w in self.warnings:
                print(f"  [!!] {w}")

        # Failures summary
        if self.failures:
            print(f"\n--- FAILURES ({len(self.failures)}) ---")
            for f in self.failures:
                print(f"  [XX] {f['name']}: {f['detail']}")

        # Overall
        pct = (passed / total * 100) if total > 0 else 0
        print(f"\n{'=' * 80}")
        print(f"RELIABILITY SCORE: {pct:.0f}% ({passed}/{total} checks passed)")
        if pct >= 80:
            print("VERDICT: Data foundation is reasonable — proceed with caution")
        elif pct >= 50:
            print("VERDICT: Significant issues — fix before building further")
        else:
            print("VERDICT: Data is NOT reliable — major rework needed")
        print("=" * 80)

        return pct


def get_db():
    """Get a database connection."""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


# =============================================================================
# CHECK 1: DATABASE COMPLETENESS
# =============================================================================

def check_database_completeness(report: ValidationReport):
    """Check if all tables exist and have data."""
    conn = get_db()
    cursor = conn.cursor()

    # Table existence and row counts
    expected_tables = ["products", "suppliers", "product_suppliers", "inventory",
                       "purchase_orders", "performance"]
    for table in expected_tables:
        cursor.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'")
        exists = cursor.fetchone()[0] > 0
        report.add_check(f"Table '{table}' exists", exists)

        if exists:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            report.set_stat(f"  {table} rows", count)

    # Products table — check for required fields with no nulls
    cursor.execute("SELECT COUNT(*) FROM products")
    total = cursor.fetchone()[0]
    report.set_stat("Total products", total)

    if total == 0:
        report.add_check("Products table has data", False, "0 products found — nothing to validate")
        conn.close()
        return

    report.add_check("Products table has data", True, f"{total} products")

    # Null checks on critical columns
    critical_cols = ["asin", "title", "current_price", "sales_rank",
                     "estimated_monthly_sales", "num_sellers", "opportunity_score"]
    for col in critical_cols:
        cursor.execute(f"SELECT COUNT(*) FROM products WHERE {col} IS NULL")
        nulls = cursor.fetchone()[0]
        report.add_check(
            f"No nulls in products.{col}",
            nulls == 0,
            f"{nulls}/{total} nulls" if nulls > 0 else ""
        )

    # Check price_history_avg (known issue)
    cursor.execute("SELECT COUNT(*) FROM products WHERE price_history_avg IS NULL")
    nulls = cursor.fetchone()[0]
    report.add_check(
        "products.price_history_avg populated",
        nulls < total,
        f"{nulls}/{total} nulls — historical averages not being stored" if nulls > 0 else ""
    )

    conn.close()


# =============================================================================
# CHECK 2: PROFIT CALCULATION AUDIT
# =============================================================================

def check_profit_calculations(report: ValidationReport):
    """Audit whether profit numbers are real or fabricated."""
    conn = get_db()
    cursor = conn.cursor()

    # Check if profit_potential is always ~45% of price (the hardcoded formula)
    cursor.execute("""
        SELECT asin, current_price, profit_potential,
               ROUND(CAST(profit_potential AS FLOAT) / CAST(current_price AS FLOAT) * 100, 1) as margin_pct
        FROM products
        WHERE current_price > 0
    """)
    rows = cursor.fetchall()

    if not rows:
        report.add_check("Profit calculations present", False, "No products with prices")
        conn.close()
        return

    margins = [r[3] for r in rows]
    avg_margin = sum(margins) / len(margins)
    margin_std = (sum((m - avg_margin) ** 2 for m in margins) / len(margins)) ** 0.5

    # If all margins cluster tightly around one value, it's a formula, not real data
    is_formulaic = margin_std < 5.0  # If std dev < 5%, margins are suspiciously uniform

    report.add_check(
        "Profit margins are based on real supplier costs (not a formula)",
        not is_formulaic,
        f"Avg margin: {avg_margin:.1f}%, Std dev: {margin_std:.1f}%\n"
        f"Margins are {'suspiciously uniform — likely using estimated_cogs = price * 0.40' if is_formulaic else 'varied enough to suggest real data'}"
    )

    # Check if any product has profit_potential <= 0
    cursor.execute("SELECT COUNT(*) FROM products WHERE profit_potential <= 0")
    unprofitable = cursor.fetchone()[0]
    total = len(rows)
    report.add_check(
        "Some products marked as unprofitable (realistic)",
        unprofitable > 0,
        f"{unprofitable}/{total} unprofitable — {'good, shows honest assessment' if unprofitable > 0 else 'ALL products show profit, which is unrealistic'}"
    )

    # Check supplier costs
    cursor.execute("""
        SELECT COUNT(*) FROM product_suppliers WHERE supplier_cost > 0
    """)
    real_costs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM product_suppliers")
    total_links = cursor.fetchone()[0]

    report.add_check(
        "Product-supplier links have real cost data",
        real_costs > 0,
        f"{real_costs}/{total_links} links have supplier_cost > 0\n"
        f"{'All costs are zero — supplier sourcing has not produced real pricing' if real_costs == 0 else ''}"
    )

    conn.close()


# =============================================================================
# CHECK 3: SALES ESTIMATION ACCURACY
# =============================================================================

def check_sales_estimation(report: ValidationReport):
    """Validate the sales rank → monthly sales estimation formula."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT asin, sales_rank, estimated_monthly_sales, category
        FROM products
        WHERE sales_rank > 0 AND estimated_monthly_sales > 0
    """)
    rows = cursor.fetchall()

    if not rows:
        report.add_check("Sales estimation data present", False)
        conn.close()
        return

    # Check if formula is simply 100000 / rank
    formula_matches = 0
    mismatches = []
    for asin, rank, est_sales, category in rows:
        expected = max(1, int(100000 / rank))
        if est_sales == expected:
            formula_matches += 1
        else:
            mismatches.append((asin, rank, est_sales, expected))

    is_simple_formula = formula_matches == len(rows)
    report.add_check(
        "Sales estimation uses category-specific models (not just 100k/rank)",
        not is_simple_formula,
        f"{formula_matches}/{len(rows)} products match the simple 100000/rank formula\n"
        f"This formula ignores category differences — rank 100 in Musical Instruments\n"
        f"means very different sales volume than rank 100 in Electronics"
    )

    # Check for unrealistic sales numbers
    high_sales = [(r[0], r[2]) for r in rows if r[2] > 5000]
    report.add_check(
        "No unrealistically high sales estimates",
        len(high_sales) <= len(rows) * 0.1,  # Allow up to 10%
        f"{len(high_sales)} products with >5000 estimated monthly sales\n"
        + ("\n".join(f"  {a}: {s} units/month" for a, s in high_sales[:5]) if high_sales else "")
    )

    conn.close()


# =============================================================================
# CHECK 4: SUPPLIER DATA QUALITY
# =============================================================================

def check_supplier_quality(report: ValidationReport):
    """Validate supplier data is real and usable."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT supplier_id, name, website, contact_email, min_order_qty, lead_time_days, notes FROM suppliers")
    suppliers = cursor.fetchall()

    if not suppliers:
        report.add_check("Suppliers exist", False, "No suppliers in database")
        conn.close()
        return

    report.set_stat("Total suppliers", len(suppliers))

    # Check for demo/placeholder suppliers
    demo_count = 0
    for s in suppliers:
        name = s[1] or ""
        notes = s[6] or ""
        if "demo" in name.lower() or "demo" in notes.lower() or "placeholder" in notes.lower():
            demo_count += 1

    report.add_check(
        "Suppliers are real (not demo/placeholder)",
        demo_count == 0,
        f"{demo_count}/{len(suppliers)} suppliers are marked as demo/placeholder"
    )

    # Check for missing critical supplier info
    missing_moq = sum(1 for s in suppliers if (s[4] or 0) == 0)
    missing_lead = sum(1 for s in suppliers if (s[5] or 0) == 0)
    missing_contact = sum(1 for s in suppliers if not s[3])

    report.add_check(
        "Suppliers have MOQ data",
        missing_moq < len(suppliers),
        f"{missing_moq}/{len(suppliers)} missing min_order_qty"
    )
    report.add_check(
        "Suppliers have lead time data",
        missing_lead < len(suppliers),
        f"{missing_lead}/{len(suppliers)} missing lead_time_days"
    )

    conn.close()


# =============================================================================
# CHECK 5: CATEGORY COVERAGE
# =============================================================================

def check_category_coverage(report: ValidationReport):
    """Check if discovery has been tested across multiple categories."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY COUNT(*) DESC")
    categories = cursor.fetchall()

    non_empty = [(c, n) for c, n in categories if c and c.strip()]
    empty_count = sum(n for c, n in categories if not c or not c.strip())

    report.set_stat("Categories found", len(non_empty))
    cat_detail = "\n".join(f"  {c}: {n} products" for c, n in non_empty)
    if empty_count:
        cat_detail += f"\n  (empty/missing category): {empty_count} products"

    report.add_check(
        "Products span multiple categories (>= 3)",
        len(non_empty) >= 3,
        f"Only {len(non_empty)} category(ies) found:\n{cat_detail}\n"
        f"System has not been validated across diverse categories"
    )

    # Check for category concentration
    if non_empty:
        top_cat_name, top_cat_count = non_empty[0]
        cursor.execute("SELECT COUNT(*) FROM products")
        total = cursor.fetchone()[0]
        concentration = top_cat_count / total * 100

        report.add_check(
            "No single category dominates (< 80%)",
            concentration < 80,
            f"'{top_cat_name}' has {concentration:.0f}% of all products ({top_cat_count}/{total})"
        )

    conn.close()


# =============================================================================
# CHECK 6: SCORING MODEL VALIDATION
# =============================================================================

def check_scoring_model(report: ValidationReport):
    """Validate the opportunity scoring model produces meaningful differentiation."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT opportunity_score FROM products ORDER BY opportunity_score")
    scores = [r[0] for r in cursor.fetchall()]

    if not scores:
        report.add_check("Scoring data present", False)
        conn.close()
        return

    min_s, max_s = min(scores), max(scores)
    avg_s = sum(scores) / len(scores)
    std_s = (sum((s - avg_s) ** 2 for s in scores) / len(scores)) ** 0.5
    score_range = max_s - min_s

    report.add_check(
        "Scores have meaningful range (spread > 30 points)",
        score_range > 30,
        f"Range: {min_s:.1f} - {max_s:.1f} (spread: {score_range:.1f})\n"
        f"Avg: {avg_s:.1f}, Std dev: {std_s:.1f}"
    )

    # Check underserved threshold
    cursor.execute("SELECT COUNT(*) FROM products WHERE is_underserved = 1")
    underserved = cursor.fetchone()[0]
    total = len(scores)
    underserved_pct = underserved / total * 100

    report.add_check(
        "Underserved ratio is selective (< 80% of products)",
        underserved_pct < 80,
        f"{underserved}/{total} ({underserved_pct:.0f}%) flagged as underserved\n"
        f"{'Too many products flagged — scoring is not selective enough' if underserved_pct >= 80 else 'Good selectivity'}"
    )

    # Score vs actual data correlation check
    cursor.execute("""
        SELECT opportunity_score, sales_rank, num_sellers, estimated_monthly_sales
        FROM products
        WHERE sales_rank > 0
        ORDER BY opportunity_score DESC
    """)
    rows = cursor.fetchall()

    # Top 5 vs bottom 5 — top should have better ranks and fewer sellers
    if len(rows) >= 10:
        top5 = rows[:5]
        bot5 = rows[-5:]

        top_avg_rank = sum(r[1] for r in top5) / 5
        bot_avg_rank = sum(r[1] for r in bot5) / 5
        top_avg_sellers = sum(r[2] for r in top5) / 5
        bot_avg_sellers = sum(r[2] for r in bot5) / 5

        rank_makes_sense = top_avg_rank < bot_avg_rank
        report.add_check(
            "High-scored products have better sales ranks than low-scored",
            rank_makes_sense,
            f"Top 5 avg rank: {top_avg_rank:.0f}, Bottom 5 avg rank: {bot_avg_rank:.0f}"
        )

    conn.close()


# =============================================================================
# CHECK 7: DATA FRESHNESS
# =============================================================================

def check_data_freshness(report: ValidationReport):
    """Check if data is recent enough to be actionable."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(last_updated), MIN(last_updated) FROM products")
    newest, oldest = cursor.fetchone()

    if not newest:
        report.add_check("Data freshness", False, "No timestamps found")
        conn.close()
        return

    try:
        newest_dt = datetime.fromisoformat(newest)
        oldest_dt = datetime.fromisoformat(oldest)
        age_days = (datetime.utcnow() - newest_dt).days
        span_days = (newest_dt - oldest_dt).days

        report.add_check(
            "Data is recent (< 7 days old)",
            age_days < 7,
            f"Newest: {newest} ({age_days} days ago)\n"
            f"Oldest: {oldest}\n"
            f"Data span: {span_days} days"
        )
    except Exception as e:
        report.add_check("Data freshness", False, f"Could not parse timestamps: {e}")

    # Check performance table (should have daily records)
    cursor.execute("SELECT COUNT(*) FROM performance")
    perf_count = cursor.fetchone()[0]
    report.add_check(
        "Performance metrics are being tracked",
        perf_count > 0,
        f"{perf_count} performance records — {'no historical tracking yet' if perf_count == 0 else 'good'}"
    )

    conn.close()


# =============================================================================
# CHECK 8: LIVE API CROSS-VALIDATION (requires API keys)
# =============================================================================

def check_live_api_data(report: ValidationReport, sample_size: int = 10):
    """Cross-check stored data against live Keepa API data."""
    conn = get_db()
    cursor = conn.cursor()

    # Pick a sample: mix of high and low scoring products
    cursor.execute("""
        SELECT asin, title, current_price, sales_rank, estimated_monthly_sales, num_sellers, opportunity_score
        FROM products
        ORDER BY opportunity_score DESC
    """)
    all_products = cursor.fetchall()
    conn.close()

    if len(all_products) == 0:
        report.add_check("Live API validation", False, "No products to validate")
        return

    # Pick top N/2 and bottom N/2
    half = sample_size // 2
    sample = all_products[:half] + all_products[-half:]

    # Try to import and use Keepa
    try:
        from src.config import settings
        import keepa

        api = keepa.Keepa(settings.keepa_api_key)
        # Keepa python library expects the string domain code directly
        domain = settings.keepa_domain  # e.g. "GB", "US", "DE"

        sample_asins = [row[0] for row in sample]
        print(f"\nQuerying Keepa for {len(sample_asins)} products...")

        try:
            live_data = api.query(sample_asins, domain=domain)
        except Exception as e:
            report.add_check("Keepa API reachable", False, str(e))
            return

        report.add_check("Keepa API reachable", True)

        if not live_data:
            report.add_check("Keepa returned data", False, "Empty response")
            return

        # Build lookup
        live_lookup = {}
        import numpy as np
        for product in live_data:
            asin = product.get("asin", "")
            data = product.get("data", {})

            def last_valid(arr):
                if arr is None or len(arr) == 0:
                    return None
                valid = [float(x) for x in arr if not np.isnan(x) and float(x) > 0]
                return valid[-1] if valid else None

            new_price = last_valid(data.get("NEW", []))
            amz_price = last_valid(data.get("AMAZON", []))
            live_price = new_price or amz_price

            sales_data = data.get("SALES", [])
            live_rank = last_valid(sales_data)

            count_new = data.get("COUNT_NEW", [])
            live_sellers = last_valid(count_new)

            live_lookup[asin] = {
                "price": live_price,
                "rank": live_rank,
                "sellers": live_sellers,
            }

        # Compare stored vs live
        price_diffs = []
        rank_diffs = []
        seller_diffs = []
        detail_lines = []

        for row in sample:
            asin, title, db_price, db_rank, db_sales, db_sellers, score = row
            live = live_lookup.get(asin)
            if not live:
                continue

            short_title = (title[:40] + "...") if len(title) > 40 else title
            line = f"\n  {asin} ({short_title})"

            if live["price"] and db_price:
                diff_pct = abs(float(db_price) - live["price"]) / live["price"] * 100
                price_diffs.append(diff_pct)
                line += f"\n    Price: DB={db_price} vs Live={live['price']:.2f} ({diff_pct:.1f}% diff)"

            if live["rank"] and db_rank:
                diff_pct = abs(db_rank - live["rank"]) / live["rank"] * 100
                rank_diffs.append(diff_pct)
                line += f"\n    Rank: DB={db_rank} vs Live={int(live['rank'])} ({diff_pct:.1f}% diff)"

            if live["sellers"] and db_sellers:
                diff = abs(db_sellers - int(live["sellers"]))
                seller_diffs.append(diff)
                line += f"\n    Sellers: DB={db_sellers} vs Live={int(live['sellers'])} (diff={diff})"

            detail_lines.append(line)

        detail = "".join(detail_lines)

        # Price accuracy
        if price_diffs:
            avg_price_diff = sum(price_diffs) / len(price_diffs)
            report.add_check(
                f"Stored prices match live data (avg diff < 10%)",
                avg_price_diff < 10,
                f"Average price difference: {avg_price_diff:.1f}%{detail}"
            )
        else:
            report.add_check("Price comparison possible", False, "No comparable price data")

        # Rank accuracy
        if rank_diffs:
            avg_rank_diff = sum(rank_diffs) / len(rank_diffs)
            report.add_check(
                f"Stored ranks match live data (avg diff < 30%)",
                avg_rank_diff < 30,
                f"Average rank difference: {avg_rank_diff:.1f}%"
            )

        # Seller count accuracy
        if seller_diffs:
            avg_seller_diff = sum(seller_diffs) / len(seller_diffs)
            report.add_check(
                f"Stored seller counts match live data (avg diff < 3)",
                avg_seller_diff < 3,
                f"Average seller count difference: {avg_seller_diff:.1f}"
            )

    except ImportError:
        report.add_warning("Could not import keepa/config — skipping live API validation")
    except Exception as e:
        report.add_warning(f"Live API validation failed: {e}")


# =============================================================================
# CHECK 9: PRICE RANGE VIABILITY
# =============================================================================

def check_price_viability(report: ValidationReport):
    """Check if products are in a viable price range for FBA profitability."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT current_price FROM products WHERE current_price > 0")
    prices = [r[0] for r in cursor.fetchall()]

    if not prices:
        report.add_check("Price viability", False, "No price data")
        conn.close()
        return

    under_5 = sum(1 for p in prices if float(p) < 5)
    under_10 = sum(1 for p in prices if float(p) < 10)
    total = len(prices)

    # Products under £5 are very hard to profit on with FBA fees
    report.add_check(
        "Most products priced above £5 (FBA viable)",
        under_5 / total < 0.3,
        f"{under_5}/{total} products priced under £5 — FBA fees make these very hard to profit on\n"
        f"{under_10}/{total} products priced under £10"
    )

    conn.close()


# =============================================================================
# CHECK 10: DUPLICATE / ANOMALY DETECTION
# =============================================================================

def check_anomalies(report: ValidationReport):
    """Detect data anomalies and duplicates."""
    conn = get_db()
    cursor = conn.cursor()

    # Duplicate ASINs (shouldn't happen with primary key, but check)
    cursor.execute("SELECT asin, COUNT(*) FROM products GROUP BY asin HAVING COUNT(*) > 1")
    dupes = cursor.fetchall()
    report.add_check("No duplicate ASINs", len(dupes) == 0,
                     f"{len(dupes)} duplicates found" if dupes else "")

    # Products with zero price
    cursor.execute("SELECT COUNT(*) FROM products WHERE current_price = 0 OR current_price IS NULL")
    zero_price = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products")
    total = cursor.fetchone()[0]
    report.add_check("No zero-price products", zero_price == 0,
                     f"{zero_price}/{total} products with zero/null price")

    # Outlier detection — sales rank
    cursor.execute("SELECT asin, sales_rank FROM products WHERE sales_rank > 500000")
    high_rank = cursor.fetchall()
    report.add_check(
        "No extreme outlier sales ranks (> 500k)",
        len(high_rank) <= total * 0.05,
        f"{len(high_rank)} products with rank > 500,000 (very low demand)"
    )

    conn.close()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Validate data reliability")
    parser.add_argument("--offline", action="store_true", help="Skip live API checks")
    parser.add_argument("--sample", type=int, default=10, help="Number of products for live validation")
    args = parser.parse_args()

    report = ValidationReport()

    print("Running data validation checks...\n")

    # Offline checks (always run)
    print("[1/9] Checking database completeness...")
    check_database_completeness(report)

    print("[2/9] Auditing profit calculations...")
    check_profit_calculations(report)

    print("[3/9] Validating sales estimation formula...")
    check_sales_estimation(report)

    print("[4/9] Checking supplier data quality...")
    check_supplier_quality(report)

    print("[5/9] Checking category coverage...")
    check_category_coverage(report)

    print("[6/9] Validating scoring model...")
    check_scoring_model(report)

    print("[7/9] Checking data freshness...")
    check_data_freshness(report)

    print("[8/9] Checking price viability...")
    check_price_viability(report)

    print("[9/9] Checking for anomalies...")
    check_anomalies(report)

    # Live API check (optional)
    if not args.offline:
        print(f"\n[LIVE] Cross-checking {args.sample} products against Keepa API...")
        check_live_api_data(report, sample_size=args.sample)
    else:
        report.add_warning("Live API validation skipped (--offline mode)")

    # Print report
    score = report.print_report()

    return 0 if score >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
