# Amazon Replens Automation System - Implementation Guide

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Phase 1: Foundation Setup](#phase-1-foundation-setup)
3. [Phase 2: Product Discovery](#phase-2-product-discovery)
4. [Phase 2 Auto: Keyword-Based Discovery](#phase-2-auto-keyword-based-discovery)
5. [Phase 3: Supplier Matching](#phase-3-supplier-matching)
6. [Phase 4: Dynamic Repricing](#phase-4-dynamic-repricing)
7. [Phase 5: Inventory Forecasting](#phase-5-inventory-forecasting)
8. [Dashboard](#dashboard)
9. [Scheduling](#scheduling)

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- SQLite (default, no setup required) or PostgreSQL
- Amazon Selling Partner API credentials
- Keepa API subscription
- Google Custom Search API key + Search Engine ID (for supplier sourcing)
- OpenAI API key (optional)

### Setup

```bash
cd replens_automation_system

# Install dependencies
uv sync

cp .env.example .env
nano .env
```

### .env Rules

The `.env` file does **not** support inline comments. Every value must be a plain value with no `#` after it:

```
# Correct
KEEPA_DOMAIN=GB
MIN_PROFIT_MARGIN=0.25

# Wrong - will cause a validation error
KEEPA_DOMAIN=GB  # 1=US, 2=GB
MIN_PROFIT_MARGIN=0.25  # 25% minimum
```

Tokens containing special characters (e.g. `|`) must be quoted:

```
AMAZON_REFRESH_TOKEN="Atzr|your_token_here"
```

### Initialise the System

```bash
uv run python -m src.phases.phase_1_setup
```

---

## Phase 1: Foundation Setup

**File:** `src/phases/phase_1_setup.py`

Performs the following steps in order:

1. Creates the `logs/` directory and configures logging
2. Validates all required settings from `.env` via Pydantic
3. Creates all database tables (SQLite by default)
4. Tests the Amazon SP-API connection (fetches inventory summaries)
5. Tests the Keepa API connection
6. Reports system status

### Running

```bash
uv run python -m src.phases.phase_1_setup
```

### Expected Output

```
[INFO] Starting Phase 1: Foundation Setup
[INFO] [1/6] Setting up logging...
[INFO] ✓ Logging configured
[INFO] [2/6] Validating configuration...
[INFO] ✓ Configuration validation passed
[INFO] [3/6] Initialising database...
[INFO] ✓ Database initialized
[INFO] [4/6] Testing Amazon SP-API connection...
[INFO] ✓ Amazon SP-API connection successful
[INFO] [5/6] Testing Keepa API connection...
[INFO] ✓ Keepa API connection successful
[INFO] ✓ All systems operational
```

### Troubleshooting

- **ValidationError (20 errors):** Your `.env` has inline comments. Remove all `# ...` text after values.
- **PermissionError on .env:** Run `sudo chown www-data:www-data .env && sudo chmod 600 .env`
- **PermissionError on logs/:** Run `sudo chown -R www-data:www-data logs/`
- **ModuleNotFoundError:** Run `uv sync` to install dependencies

---

## Phase 2: Product Discovery

**File:** `src/phases/phase_2_discovery.py`

Analyses a list of ASINs using Keepa to identify replenishable opportunities.

### How It Works

1. Fetches product data from the Keepa API for each ASIN
2. Extracts features: price, price stability, sales rank, seller count, estimated monthly sales
3. Estimates profitability (assumes 40% COGS, uses Amazon fee estimates)
4. Scores each product using the weighted opportunity model (0–100)
5. Saves results to the `products` table in the database

### Opportunity Scoring Model

Located in `src/models/discovery_model.py`. Uses a fixed weighted formula:

```
Score = 0.15 × price_stability
      + 0.20 × low_competition      (< 5 sellers)
      + 0.20 × good_sales_rank      (< 50,000 rank)
      + 0.20 × sales_velocity       (normalised)
      + 0.15 × profit_margin        (normalised)
      + 0.10 × roi                  (normalised)
```

Penalties applied if:
- Profit margin < `MIN_PROFIT_MARGIN` → score × 0.5
- ROI < `MIN_ROI` → score × 0.5
- Monthly sales < `MIN_SALES_VELOCITY` → score × 0.5

Products scoring ≥ 60 are flagged as `is_underserved = True`.

### Running

```bash
uv run python -m src.phases.phase_2_discovery
```

### Customising Thresholds

Edit `.env`:

```
MIN_PROFIT_MARGIN=0.25
MIN_ROI=1.0
MIN_SALES_VELOCITY=10
```

---

## Phase 2 Auto: Keyword-Based Discovery

**File:** `src/phases/phase_2_auto_discovery.py`

Automatically finds ASINs by searching the Amazon Catalog API with keywords, then passes them to the Phase 2 discovery engine.

### Usage

```bash
# Search by custom keywords
uv run python -m src.phases.phase_2_auto_discovery --keywords "violin rosin" "guitar strings" --max 50

# Search by built-in category
uv run python -m src.phases.phase_2_auto_discovery --categories music electronics --max 50

# Default (no arguments): uses music/instrument keywords
uv run python -m src.phases.phase_2_auto_discovery --max 50
```

### Arguments

| Argument | Description |
|---|---|
| `--keywords` | One or more search terms |
| `--categories` | One or more built-in categories |
| `--max` | Max products to analyse (default: 50) |

### Built-in Categories

| Category | Keywords searched |
|---|---|
| `electronics` | wireless earbuds, phone charger, bluetooth speaker, power bank |
| `home` | kitchen organizer, storage bins, cleaning supplies, home decor |
| `beauty` | skincare, makeup brush, hair care, beauty tools |
| `sports` | fitness tracker, yoga mat, resistance bands, water bottle |
| `toys` | educational toys, building blocks, puzzle games, stuffed animals |
| `pet` | dog toys, cat treats, pet grooming, pet accessories |
| `office` | desk organizer, notebook, pens, office supplies |
| `automotive` | car accessories, phone mount, car charger, cleaning tools |
| `music` | guitar strings, music accessories, instrument care, audio cables |
| `health` | vitamins, fitness supplement, health monitor, wellness products |

### Default Keywords (no arguments)

```
violin accessories, guitar accessories, music instrument care, violin rosin, instrument strings
```

---

## Phase 3: Supplier Matching

**File:** `src/phases/phase_3_sourcing_google.py`

Uses the Google Custom Search API to find suppliers on B2B platforms:
- Alibaba.com
- GlobalSources.com
- Made-in-China.com
- TradeKey.com
- DHgate.com

**Requirements:** `GOOGLE_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` set in `.env`.

```bash
uv run python -m src.phases.phase_3_sourcing_google
```

### Profitability Calculation

For each supplier found:

```
Total Cost    = Supplier Cost + Shipping Cost
Net Profit    = Selling Price - Total Cost - Amazon Fees
Profit Margin = Net Profit / Selling Price
ROI           = Net Profit / Total Cost
```

Results are saved to the `product_suppliers` table.

### Utility Tools for Suppliers

```bash
# Add suppliers via form
uv run python tools/supplier_entry_form.py

# Import from CSV
uv run python tools/import_suppliers_csv.py

# View all suppliers
uv run python tools/show_suppliers.py

# Remove demo/test suppliers
uv run python tools/remove_demo_suppliers.py
```

---

## Phase 4: Dynamic Repricing

**File:** `src/phases/phase_4_repricing.py`

Monitors competitor prices and adjusts your prices to target Buy Box ownership.

### How It Works

1. Reads active products from the database
2. Fetches current competitor prices via Keepa API and Amazon SP-API
3. Applies repricing rules with margin protection:
   - Target: undercut competitor by `PRICE_ADJUSTMENT_AMOUNT` (default £0.01)
   - Floor: minimum price = cost + fees + target margin
   - Ceiling: maximum price = cost × `MAX_PRICE_MULTIPLIER` (default 1.5)
4. Submits price updates via Amazon SP-API

### Configuration

```
TARGET_BUY_BOX_WIN_RATE=0.90
PRICE_ADJUSTMENT_FREQUENCY=hourly
PRICE_ADJUSTMENT_AMOUNT=0.01
MAX_PRICE_MULTIPLIER=1.5
MIN_PRICE_CHANGE_PERCENT=0.01
```

### Running

```bash
uv run python -m src.phases.phase_4_repricing
```

---

## Phase 5: Inventory Forecasting

**File:** `src/phases/phase_5_forecasting.py`

**Status: Not yet implemented.** The file exists as a placeholder and logs a "not yet implemented" message when run.

Planned features:
- Time-series demand forecasting
- Automated reorder point calculation
- Safety stock management
- Purchase order generation

---

## Dashboard

**File:** `src/dashboard/app.py`

Streamlit-based web dashboard providing real-time visibility into system metrics.

### Running

```bash
uv run streamlit run src/dashboard/app.py
```

Access at `http://localhost:8501` (or your server's IP/domain on port 8501).

### Dashboard Sections

1. **Overview** – KPIs: revenue, profit, ROI, inventory turnover, Buy Box %
2. **Products** – All tracked products with scores and metrics
3. **Opportunities** – Newly discovered underserved products (score ≥ 60)
4. **Inventory** – Stock levels and reorder alerts
5. **Suppliers** – Supplier list with pricing and profitability
6. **Performance** – Charts and trend analysis

### Keeping It Running (Ubuntu)

```bash
# Run in background with nohup
nohup uv run streamlit run src/dashboard/app.py --server.port 8501 &

```
