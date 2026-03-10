# Amazon Replens Automation System

**Automated Amazon FBA Business Management Platform**

A Python system for automating the Amazon Replens workflow: product discovery, supplier sourcing, dynamic repricing, and inventory management, with a Streamlit dashboard.

## Features

- **Product Discovery:** Weighted-score identification of underserved Amazon listings via Keepa API
- **Auto Discovery:** Keyword and category-based product scanning via Amazon Catalog API
- **Supplier Matching:** Supplier discovery via Google Custom Search API and OpenAI (optional)
- **Dynamic Repricing:** Rule-based price optimisation for Buy Box dominance
- **Real-Time Dashboard:** KPI monitoring built with Streamlit

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AMAZON REPLENS AUTOMATION                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  Product     │  │  Supplier    │  │  Dynamic     │           │
│  │  Discovery   │→ │  Matching    │→ │  Repricing   │           │
│  │  Engine      │  │  Engine      │  │  Engine      │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │    Performance Monitoring & Analytics Dashboard   │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐           │
│  │         Database (SQLite / PostgreSQL)           │           │
│  │  Products | Suppliers | Inventory | POs | KPIs  │           │
│  └──────────────────────────────────────────────────┘           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- SQLite (default, included) or PostgreSQL
- Amazon SP-API credentials
- Keepa API key
- Google Custom Search API key (for supplier sourcing)
- OpenAI API key (optional, for AI supplier matching)

### Installation

```bash
cd replens_automation_system

# Install dependencies
uv sync

cp .env.example .env
nano .env
```

### .env File Format

Values must **not** contain inline comments. Use plain values only:

```
KEEPA_DOMAIN=GB
MIN_PROFIT_MARGIN=0.25
AMAZON_REFRESH_TOKEN="Atzr|your_token_here"
```

### Running the System

```bash
# Phase 1: Initialise database and test API connections
uv run python -m src.phases.phase_1_setup

# Phase 2: Discover products from a predefined ASIN list
uv run python -m src.phases.phase_2_discovery

# Phase 2 (Auto): Discover products via keyword or category search
uv run python -m src.phases.phase_2_auto_discovery --keywords "violin accessories" --max 50
uv run python -m src.phases.phase_2_auto_discovery --categories electronics home --max 50

# Phase 3: Find suppliers via Google Custom Search
uv run python -m src.phases.phase_3_sourcing_google

# Phase 4: Run dynamic repricing
uv run python -m src.phases.phase_4_repricing

# Start dashboard
uv run streamlit run src/dashboard/app.py
```

## Project Structure

```
replens_automation_system/
├── src/
│   ├── main.py                              # Runs all phases sequentially
│   ├── config.py                            # Pydantic settings loaded from .env
│   ├── database.py                          # SQLAlchemy ORM models and operations
│   ├── api_wrappers/
│   │   ├── amazon_sp_api.py                 # Amazon SP-API integration
│   │   ├── keepa_api.py                     # Keepa API integration
│   │   ├── google_shopping_finder.py        # Google Custom Search for suppliers
│   │   ├── openai_supplier_finder.py        # OpenAI-based supplier matching
│   │   ├── seller_metrics.py                # Seller performance metrics
│   │   └── supplier_metrics.py              # Supplier performance metrics
│   ├── phases/
│   │   ├── phase_1_setup.py              # DB init, API tests, config validation
│   │   ├── phase_2_discovery.py          # Product discovery engine (Keepa)
│   │   ├── phase_2_auto_discovery.py     # Auto discovery via keyword search
│   │   ├── phase_3_sourcing_google.py    # Supplier sourcing via Google Search
│   │   ├── phase_4_repricing.py          # Dynamic repricing engine
│   │   └── phase_5_forecasting.py        # Inventory forecasting (not yet implemented)
│   ├── models/
│   │   └── discovery_model.py               # Weighted opportunity scoring model
│   └── dashboard/
│       └── app.py                           # Streamlit dashboard
├── tools/                                   # Utility and diagnostic scripts
│   ├── clear_products.py
│   ├── clear_suppliers.py
│   └── ...
├── docs/                                    # Documentation
├── logs/                                    # Log files (auto-created by phase_1_setup)
├── replens_automation.db                    # SQLite database
├── pyproject.toml
├── .env.example
└── README.md
```

## Opportunity Scoring

Products are scored 0–100 using a weighted formula:

```
Score = 0.15 × price_stability
      + 0.20 × low_competition
      + 0.20 × good_sales_rank
      + 0.20 × sales_velocity
      + 0.15 × profit_margin
      + 0.10 × roi
```

Products scoring ≥ 60 are flagged as underserved opportunities.

Low-margin or low-ROI products receive a 50% score penalty. Products below `MIN_SALES_VELOCITY` are also penalised.

## Key Configuration (`.env`)

| Setting | Default | Description |
|---|---|---|
| `MIN_PROFIT_MARGIN` | `0.25` | Minimum 25% profit margin |
| `MIN_ROI` | `1.0` | Minimum 100% ROI |
| `MIN_SALES_VELOCITY` | `10` | Minimum units/month |
| `KEEPA_DOMAIN` | `GB` | Amazon marketplace (GB = UK) |
| `AMAZON_REGION` | `EU` | SP-API region |

## Auto Discovery Keywords

Built-in categories for `--categories` flag:

| Category | Example keywords |
|---|---|
| `electronics` | wireless earbuds, phone charger, bluetooth speaker |
| `home` | kitchen organizer, storage bins, cleaning supplies |
| `beauty` | skincare, makeup brush, hair care |
| `sports` | fitness tracker, yoga mat, resistance bands |
| `toys` | educational toys, building blocks, puzzle games |
| `pet` | dog toys, cat treats, pet grooming |
| `office` | desk organizer, notebook, pens |
| `automotive` | car accessories, phone mount, car charger |
| `music` | guitar strings, music accessories, audio cables |
| `health` | vitamins, fitness supplement, health monitor |

Default (no arguments): searches music/instrument keywords.

## Documentation

- [Implementation Guide](docs/IMPLEMENTATION_GUIDE.md)
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Database Schema](docs/DATABASE_SCHEMA.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Operations Manual](docs/OPERATIONS.md)

## License

Proprietary - For personal use only.
