# Data Integrity Audit Report

**Date:** 2026-03-13
**Database:** `replens_automation.db` (SQLite)
**Scope:** Full codebase and database review for dummy content, hardcoded values, and false data claims

---

## Executive Summary

While product data (ASINs, titles, prices) is real and sourced from the Keepa API, **nearly all downstream data is fabricated, hardcoded, or estimated using fixed formulas**. The system is running in demo mode without live API connections. Any business decisions based on current financial metrics would be based on fabricated estimates, not real data.

---

## 1. Database Findings

### 1.1 Products (101 rows) — REAL

- ASINs, titles, and prices are genuine Amazon UK listings scraped via Keepa.
- Price range: £2.70 – £169.89 (plausible).
- **Minor issues:**
  - All 101 products have `status = "active"` — none rejected or archived (unrealistic for a real pipeline).
  - All created within 3 days (2026-03-10 to 2026-03-12).
  - 1 product has an empty category.
  - 55 of 101 are in "Musical Instruments & DJ" (heavily skewed).

### 1.2 Suppliers (2 rows) — FAKE

Both suppliers are explicitly labelled as demo placeholders:

| ID | Name | Notes |
|----|------|-------|
| 1 | Alibaba - Demo Alibaba Supplier | "Demo supplier - Google API not configured" |
| 2 | Global Sources - Demo Global Sources Supplier | "Demo supplier - Google API not configured" |

Both have:
- `contact_email = NULL`
- `min_order_qty = 0`, `lead_time_days = 0`
- `reliability_score = 0.0`, `on_time_delivery_rate = 0.0`
- `total_orders = 0`

**Source:** `src/phases/phase_3_sourcing_google.py:360-384` — `_get_demo_suppliers()` fallback function.

### 1.3 Supplier Costs (70 rows) — FORMULAIC / NOT REAL QUOTES

- **Every single supplier cost is exactly 30% of the product's Amazon price.**
- All 70 out of 70 records match the formula: `supplier_cost = current_price × 0.30`
- Every shipping cost is identically £1.50 (hardcoded default).
- Both "suppliers" always have identical costs per product (35 pairs).
- Many products show negative profit margins (up to -80%).

**Source:** `src/config.py:213-229` — `WHOLESALE_COST_RATIOS` constant defaults to 0.30.

### 1.4 Sales & Performance (288 rows) — ZERO ACTUAL DATA

- `units_sold = 0` for all 288 records
- `revenue = 0` for all 288 records
- `buy_box_percentage = 0.0` for all 288 records
- `buy_box_owned = 0` for all 288 records
- `cost_of_goods` and `amazon_fees` are populated (estimated), but `net_profit` is computed from zero revenue — meaningless.
- All data spans only 2 days (2026-03-11 to 2026-03-12).

### 1.5 Inventory (73 rows) — EFFECTIVELY EMPTY

- 72 out of 73 products have `current_stock = 0`
- Only 1 product has stock = 12
- 71 items flagged `needs_reorder = 1` despite having no stock history
- `last_restock_date = NULL` for all records
- `forecasted_stock_30d = 0` and `forecasted_stock_60d = 0` for nearly all

### 1.6 Purchase Orders — COMPLETELY EMPTY

- Zero rows. No purchase orders have ever been created.

---

## 2. Hardcoded Values in Code

### 2.1 Wholesale Cost Estimation

**File:** `src/config.py:213-229`

Category-based wholesale ratios used as if they are real supplier costs:

```python
WHOLESALE_COST_RATIOS = {
    'default': 0.30,        # 30% of retail price
    'Electronics': 0.45,
    'Home & Kitchen': 0.35,
    # ... etc.
}
```

**Impact:** All "supplier costs" in the database are derived from these ratios, not from real supplier quotes.

### 2.2 COGS Estimation in Discovery Phase

**File:** `src/phases/phase_2_discovery.py:180-190`

Estimates Cost of Goods Sold as 50% of retail price, then applies a 40% "uncertainty discount". This is pure guesswork with no validation against real data.

### 2.3 Fixed Shipping Costs

**File:** `src/config.py:233-239`

```
China Standard Shipping: £1.50
UK Domestic: £0.80
```

Every product uses the same shipping cost regardless of weight, size, or actual shipping quotes.

### 2.4 Dashboard Profit Display

**File:** `src/dashboard/app.py:246`

The dashboard displays "Est. 30-Day Profit" using a **hardcoded 25% flat margin** for all products:

```python
estimated_profit = product.current_price * 0.25
```

This figure has no relationship to actual costs, fees, or margins.

### 2.5 Sales Volume Estimation

**File:** `src/config.py:244-259`

Sales rank is converted to estimated sales volume using hardcoded power-law formulas. These are not validated against actual Amazon sales data.

### 2.6 SP-API Sales Data Stub

**File:** `src/api_wrappers/amazon_sp_api.py:491`

The `get_sales_data()` method is a stub that returns an empty dictionary `{}`. No real sales data is ever fetched.

### 2.7 Default Supplier Reliability

**File:** `src/phases/phase_3_sourcing_google.py:139-140`

All new suppliers receive default scores regardless of actual performance:
- Reliability score: 50.0
- On-time delivery rate: 0.85 (85%)

---

## 3. Missing Live API Connections

| API | Status | Impact |
|-----|--------|--------|
| Google Custom Search (supplier discovery) | Not configured | Falls back to demo suppliers |
| Amazon SP-API (sales data) | Stub/empty | No real sales or revenue data |
| Amazon SP-API (feeds) | Not tested | No actual repricing or inventory updates sent |

---

## 4. Summary Table

| Data Layer | Real or Fake? | Evidence |
|---|---|---|
| Product ASINs / titles | Real | Genuine Amazon product names from Keepa |
| Product prices | Real | Plausible UK prices from Keepa |
| Suppliers | **Fake** | Explicitly "Demo" in names and notes |
| Supplier costs | **Formulaic** | 100% match `price × 0.30` |
| Shipping costs | **Hardcoded** | All £1.50 |
| Sales / revenue | **Zero** | 288 records, all zeros |
| Inventory | **Empty** | 72/73 have zero stock |
| Purchase orders | **Empty** | 0 rows |
| Dashboard profit | **Hardcoded** | Flat 25% margin for all products |
| Sales volume estimates | **Unvalidated** | Power-law formula, no real data backing |

---

## 5. Recommendations

1. **Label all estimated values** — Add `[ESTIMATED]` tags in the UI/dashboard wherever hardcoded or formula-derived values are displayed.
2. **Configure Google Custom Search API** — Replace demo suppliers with real supplier discovery.
3. **Implement SP-API sales data** — Replace the stub `get_sales_data()` with a real implementation to get actual sales, revenue, and Buy Box data.
4. **Get real supplier quotes** — Replace the `WHOLESALE_COST_RATIOS` formula with actual sourcing data from suppliers.
5. **Add data source indicators** — In the database schema, add a column (e.g., `data_source`) to distinguish real vs. estimated values.
6. **Validate sales rank formulas** — Back-test the power-law sales volume estimation against real sales data before relying on it.
7. **Remove or clearly flag demo suppliers** — Prevent demo data from appearing in production reports or decision-making workflows.
