# Amazon Replens Automation System - Operations Manual

## 1. Daily Operations

### 1.1. Checking System Status

```bash
# View recent logs
tail -f /var/www/html/replen/home/ubuntu/replens_automation_system/logs/replens_automation.log

# View discovery-specific logs
tail -f /var/www/html/replen/home/ubuntu/replens_automation_system/logs/discovery.log
```

### 1.2. Triggering a Manual Discovery Run

```bash
# Run directly in your terminal
cd /var/www/html/replen/home/ubuntu/replens_automation_system
uv run python -m src.phases.phase_2_auto_discovery --max 50
```

### 1.3. Reviewing Opportunities in the Dashboard

1. Open `http://your-server-ip:8501`
2. Navigate to the **Opportunities** tab
3. Review products with score ≥ 60 (flagged as underserved)
4. Check supplier matches in the **Suppliers** tab

### 1.4. Checking the Database Directly

```bash
cd /var/www/html/replen/home/ubuntu/replens_automation_system

# Open SQLite
sqlite3 replens_automation.db

# Useful queries
SELECT asin, title, opportunity_score, is_underserved FROM products ORDER BY opportunity_score DESC LIMIT 10;
SELECT COUNT(*) FROM products WHERE is_underserved = 1;
SELECT COUNT(*) FROM suppliers WHERE status = 'active';
SELECT COUNT(*) FROM product_suppliers;
.quit
```

---

## 2. Running Individual Phases

All phases should be run from the project root:

```bash
cd /var/www/html/replen/home/ubuntu/replens_automation_system
```

| Phase | Command |
|---|---|
| Phase 1 – Setup & API test | `uv run python -m src.phases.phase_1_setup` |
| Phase 2 – Discovery (ASIN list) | `uv run python -m src.phases.phase_2_discovery` |
| Phase 2 – Auto discovery (keywords) | `uv run python -m src.phases.phase_2_auto_discovery --max 50` |
| Phase 3 – Sourcing (Google) | `uv run python -m src.phases.phase_3_sourcing_google` |
| Phase 4 – Repricing | `uv run python -m src.phases.phase_4_repricing` |
| Dashboard | `uv run streamlit run src/dashboard/app.py` |

---

## 3. Supplier Management

### Adding Suppliers

```bash
# Interactive form
uv run python tools/supplier_entry_form.py

# Bulk import from CSV
uv run python tools/import_suppliers_csv.py
```

### Viewing and Cleaning Suppliers

```bash
# List all suppliers
uv run python tools/show_suppliers.py

# Show supplier URLs
uv run python tools/show_supplier_urls.py

# Check supplier data quality
uv run python tools/check_supplier_data.py

# Remove demo/test suppliers
uv run python tools/remove_demo_suppliers.py

# Clean all suppliers (use with caution)
uv run python tools/clean_suppliers.py
```

---

## 4. Inventory Tools

```bash
# Check inventory type (FBA vs FBM)
uv run python tools/check_inventory_type.py

# Debug inventory data
uv run python tools/debug_inventory.py

# Get FBM inventory
uv run python tools/get_fbm_inventory.py

# Set FBM inventory manually
uv run python tools/set_fbm_inventory_manual.py

# Test inventory API
uv run python tools/test_inventory_api.py
```

---

## 5. Price Diagnostics

```bash
# Check Keepa prices for products in database
uv run python tools/check_keepa_prices.py

# Show product prices
uv run python tools/show_product_prices.py

# Check price for a specific ASIN
uv run python tools/check_asin_price.py

# Inspect Keepa data structure
uv run python tools/inspect_keepa_structure.py
```

---

## 6. Database Management

### Backup

```bash
# SQLite backup (copy the file)
cp /var/www/html/replen/home/ubuntu/replens_automation_system/replens_automation.db \
   /var/www/html/replen/home/ubuntu/replens_automation_system/replens_automation_$(date +%Y%m%d).db.bak
```

### Clear Products (use with caution)

```bash
uv run python tools/clear_products.py
```

### Reinitialise Database

```bash
uv run python -m src.phases.phase_1_setup
```

---

## 7. Maintenance

### Updating Dependencies

```bash
uv sync
```

### Rotating API Keys

After updating credentials in `.env`, restart any long-running services:

```bash
sudo systemctl restart replens-dashboard
```

The discovery service reads `.env` fresh on each run, so no restart needed there.

### Log Rotation

Logs are written to `logs/replens_automation.log` and `logs/discovery.log`. To prevent them growing indefinitely, add a logrotate config:

```bash
sudo nano /etc/logrotate.d/replens
```

```
/var/www/html/replen/home/ubuntu/replens_automation_system/logs/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

---

## 8. Troubleshooting

### Discovery service fails

```bash
# See the actual Python error
sudo -u www-data \
  PYTHONPATH=/var/www/html/replen/home/ubuntu/replens_automation_system \
  uv run python \
  -m src.phases.phase_2_auto_discovery --max 50
```

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | Dependencies not installed | Run `uv sync` |
| `PermissionError: .env` | www-data can't read .env | `sudo chown www-data .env && chmod 600 .env` |
| `PermissionError: logs/` | www-data can't write logs | `sudo chown -R www-data logs/` |
| `ValidationError` | Inline comments in .env | Remove all `# ...` after values |
| `Field required: amazon_refresh_token` | `|` in token breaks parsing | Wrap in quotes: `"Atzr|..."` |
| `No products found` | Keywords returned no results | Try different keywords or increase `--max` |
| Dashboard shows no data | Database empty | Run Phase 1 and Phase 2 first |
