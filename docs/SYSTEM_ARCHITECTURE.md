# Amazon Replens Automation System - System Architecture

## 1. High-Level Architecture

The system is composed of five phases, a SQLite/PostgreSQL database, API wrappers for external services, and a Streamlit dashboard.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Ubuntu Server                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │                    Python Phases                        │     │
│  │                                                         │     │
│  │  phase_1_setup  →  phase_2_auto_discovery               │     │
│  │                         │                               │     │
│  │                    phase_2_discovery                    │     │
│  │                         │                               │     │
│  │               phase_3_sourcing_google                   │     │
│  │                         │                               │     │
│  │                  phase_4_repricing                      │     │
│  │                         │                               │     │
│  │              phase_5_forecasting (planned)              │     │
│  └─────────────────────────────────────────────────────────┘     │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────────────┐    ┌──────────────────────────┐         │
│  │  SQLite Database    │    │  Streamlit Dashboard     │         │
│  │  replens_automation │←───│  src/dashboard/app.py   │         │
│  │  .db                │    │  :8501                   │         │
│  └─────────────────────┘    └──────────────────────────┘         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│           External APIs                │
│                                        │
│  Amazon SP-API  (EU region)            │
│  Keepa API      (GB/UK domain)         │
│  Google Custom Search API              │
│  OpenAI API     (optional)             │
└────────────────────────────────────────┘
```

## 2. Component Breakdown

### 2.1. API Wrappers (`src/api_wrappers/`)

| File | Responsibility |
|---|---|
| `amazon_sp_api.py` | Amazon SP-API: inventory, pricing, fee estimates, catalog search |
| `keepa_api.py` | Keepa API: historical price, sales rank, seller count data |
| `google_shopping_finder.py` | Google Custom Search: B2B supplier discovery |
| `openai_supplier_finder.py` | OpenAI: AI-assisted supplier matching (optional) |
| `seller_metrics.py` | Seller performance metrics for the dashboard |
| `supplier_metrics.py` | Supplier performance metrics for the dashboard |

### 2.3. Database (`src/database.py`)

- **ORM:** SQLAlchemy
- **Default:** SQLite (`replens_automation.db` in project root)
- **Production option:** PostgreSQL (set `DATABASE_URL` in `.env`)

Tables: `products`, `suppliers`, `product_suppliers`, `inventory`, `purchase_orders`, `performance`

See `docs/DATABASE_SCHEMA.md` for full schema.

### 2.4. Phases (`src/phases/`)

#### Phase 1: Foundation Setup (`phase_1_setup.py`)
- Creates the database schema
- Tests Amazon SP-API and Keepa API connections
- Validates `.env` configuration

#### Phase 2: Product Discovery (`phase_2_discovery.py`)
- Queries Keepa API for product data by ASIN
- Extracts features: price, stability, sales rank, seller count, sales velocity
- Estimates profitability (COGS assumed at 40% of selling price)
- Scores products using the weighted model in `src/models/discovery_model.py`
- Saves results to the `products` table

#### Phase 2 Auto: Keyword Discovery (`phase_2_auto_discovery.py`)
- Searches the Amazon Catalog API using keywords
- Collects ASINs from results
- Passes ASINs to the Phase 2 discovery engine
- Supports `--keywords`, `--categories`, and `--max` arguments

#### Phase 3: Supplier Matching (multiple variants)

| File | Method |
|---|---|
| `phase_3_sourcing_google.py` | Google Custom Search API across B2B platforms |

All variants save supplier links and profitability data to `product_suppliers`.

#### Phase 4: Dynamic Repricing (`phase_4_repricing.py`)
- Monitors competitor prices via Keepa and SP-API
- Applies custom repricing rules with margin floor enforcement
- Submits price updates via Amazon SP-API

#### Phase 5: Inventory Forecasting (`phase_5_forecasting.py`)
- **Not yet implemented** — placeholder only

### 2.5. Opportunity Scoring Model (`src/models/discovery_model.py`)

A weighted linear scoring model (not a trained ML model). Weights:

| Feature | Weight |
|---|---|
| Price stability | 0.15 |
| Low competition (< 5 sellers) | 0.20 |
| Good sales rank (< 50,000) | 0.20 |
| Sales velocity | 0.20 |
| Profit margin | 0.15 |
| ROI | 0.10 |

Score penalties (× 0.5) are applied for low margin, low ROI, or low sales velocity.

### 2.6. Dashboard (`src/dashboard/app.py`)

- **Technology:** Streamlit
- **Port:** 8501
- **Data sources:** SQLite database + Amazon SP-API (via `seller_metrics.py`)
- **Refresh:** Cached data refreshes every 300 seconds

## 3. Data Flow

```
1. phase_2_auto_discovery searches Amazon Catalog API by keyword
         │
3. ASINs passed to phase_2_discovery
         │
4. Keepa API queried for each ASIN → features extracted → scored
         │
5. Opportunities saved to products table (SQLite)
         │
6. phase_3_sourcing_google finds suppliers via Google Custom Search
         │
7. Supplier + profitability data saved to product_suppliers table
         │
8. phase_4_repricing reads products, fetches competitor prices,
   calculates new prices, submits to Amazon SP-API
         │
9. Dashboard reads from SQLite and SP-API continuously
```

## 4. Configuration

All configuration is via `.env` (loaded by Pydantic `Settings` class in `src/config.py`). No inline comments are permitted in `.env` values.

Key settings:

| Setting | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./replens_automation.db` | Relative to project root |
| `AMAZON_REGION` | `EU` | EU = Amazon UK/Europe |
| `KEEPA_DOMAIN` | `GB` | GB = Amazon UK |
| `KEEPA_RATE_LIMIT` | `10` | Requests per second |
| `AMAZON_RATE_LIMIT` | `5` | Requests per second |
