# Amazon Replens Automation System - Deployment Guide

This guide covers deploying the system on an Ubuntu server using uv.

## 1. Prerequisites

- Ubuntu 20.04+ server
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- Project files at `/var/www/html/replen/home/ubuntu/replens_automation_system`
- A configured `.env` file (see `.env.example`)

## 2. Initial Setup

### 2.1. Install uv and sync dependencies

```bash
cd /var/www/html/replen/home/ubuntu/replens_automation_system

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies
uv sync
```

### 2.2. Configure environment

```bash
cp .env.example .env
nano .env
```

**Important:** `.env` values must not contain inline comments. Use plain values:

```
# Correct
KEEPA_DOMAIN=GB
MIN_PROFIT_MARGIN=0.25
AMAZON_REFRESH_TOKEN="Atzr|your_token_here"

# Wrong (causes ValidationError)
KEEPA_DOMAIN=GB  # UK marketplace
```

### 2.3. Set file permissions

The service runs as `www-data`. Grant it access to the project files:

```bash
# .env (credentials — restrict to owner only)
sudo chown www-data:www-data .env
sudo chmod 600 .env

# logs directory
sudo mkdir -p logs
sudo chown -R www-data:www-data logs

# database file
sudo chown www-data:www-data replens_automation.db 2>/dev/null || true
```

### 2.4. Initialise the database

```bash
sudo -u www-data PYTHONPATH=/var/www/html/replen/home/ubuntu/replens_automation_system \
  uv run python -m src.phases.phase_1_setup
```

---

## 3. Dashboard

Run the Streamlit dashboard manually or as a background process:

```bash
cd /var/www/html/replen/home/ubuntu/replens_automation_system

# Foreground (for testing)
uv run streamlit run src/dashboard/app.py

# Background
nohup uv run streamlit run src/dashboard/app.py --server.port 8501 > logs/dashboard.log 2>&1 &
```

Access at `http://your-server-ip:8501`.

To keep the dashboard running after logout, use a terminal multiplexer (tmux/screen).

---

## 4. Updating the System

```bash
cd /var/www/html/replen/home/ubuntu/replens_automation_system

# Pull latest files (if using git)
git pull

# Install any new/updated dependencies
uv sync
```

---

## 5. Troubleshooting

| Error | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'numpy'` | Run `uv sync` to install dependencies |
| `PermissionError: .env` | `sudo chown www-data:www-data .env && sudo chmod 600 .env` |
| `PermissionError: logs/` | `sudo chown -R www-data:www-data logs/` |
| `ValidationError: 20 errors` | Remove all inline comments from `.env` values |
| `amazon_refresh_token: Field required` | Wrap token in quotes: `AMAZON_REFRESH_TOKEN="Atzr|..."` |
| Service exits with code=1 | Run manually as www-data to see traceback: `sudo -u www-data PYTHONPATH=... uv run python -m src.phases.phase_2_auto_discovery` |
