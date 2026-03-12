"""
System Health Check Tool

Validates connectivity and status of all system components:
- Database connectivity and table counts
- API key validity (Keepa, SP-API, Google)
- Google API quota status
- Data freshness (last update timestamps)
- Pipeline status summary

Usage:
    uv run python tools/health_check.py           # Full health check
    uv run python tools/health_check.py --quick    # Quick connectivity check
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import SessionLocal, Product, Supplier, ProductSupplier, Inventory, PurchaseOrder, Performance
from src.config import settings

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class HealthCheck:
    """System health check with structured status reporting."""

    def __init__(self):
        self.results = {}
        self.warnings = []
        self.errors = []

    def check_database(self):
        """Check database connectivity and table counts."""
        status = {'status': 'unknown', 'tables': {}}
        try:
            session = SessionLocal()
            status['tables'] = {
                'products': session.query(Product).count(),
                'products_active': session.query(Product).filter(Product.status == 'active').count(),
                'suppliers': session.query(Supplier).count(),
                'product_suppliers': session.query(ProductSupplier).count(),
                'with_costs': session.query(ProductSupplier).filter(ProductSupplier.supplier_cost > 0).count(),
                'inventory': session.query(Inventory).count(),
                'purchase_orders': session.query(PurchaseOrder).count(),
                'performance': session.query(Performance).count(),
            }

            # Check data freshness
            latest_product = session.query(Product).order_by(Product.last_updated.desc()).first()
            if latest_product and latest_product.last_updated:
                status['last_product_update'] = latest_product.last_updated.isoformat()
                age = datetime.utcnow() - latest_product.last_updated
                if age > timedelta(days=7):
                    self.warnings.append(f"Product data is {age.days} days old")

            session.close()
            status['status'] = 'healthy'
        except Exception as e:
            status['status'] = 'error'
            status['error'] = str(e)
            self.errors.append(f"Database: {e}")

        self.results['database'] = status

    def check_keepa_api(self):
        """Check Keepa API connectivity."""
        status = {'status': 'unknown'}
        try:
            if not settings.keepa_api_key:
                status['status'] = 'not_configured'
                self.warnings.append("Keepa API key not set")
            else:
                from src.api_wrappers.keepa_api import KeepaAPI
                api = KeepaAPI()
                status['status'] = 'healthy'
                status['domain'] = settings.keepa_domain
                # Check tokens remaining
                if hasattr(api.api, 'tokens_left'):
                    status['tokens_remaining'] = api.api.tokens_left
        except Exception as e:
            status['status'] = 'error'
            status['error'] = str(e)
            self.errors.append(f"Keepa API: {e}")

        self.results['keepa_api'] = status

    def check_sp_api(self):
        """Check Amazon SP-API connectivity."""
        status = {'status': 'unknown'}
        try:
            required = [settings.amazon_client_id, settings.amazon_client_secret,
                        settings.amazon_refresh_token, settings.amazon_seller_id]
            if not all(required):
                status['status'] = 'not_configured'
                self.warnings.append("SP-API credentials incomplete")
            else:
                from src.api_wrappers.amazon_sp_api import AmazonSPAPI
                api = AmazonSPAPI()
                status['status'] = 'healthy'
                status['region'] = settings.amazon_region
                status['token_valid'] = api.access_token is not None
        except Exception as e:
            status['status'] = 'error'
            status['error'] = str(e)
            self.errors.append(f"SP-API: {e}")

        self.results['sp_api'] = status

    def check_google_api(self):
        """Check Google Custom Search API and quota."""
        status = {'status': 'unknown'}
        try:
            if not settings.google_api_key or not settings.google_search_engine_id:
                status['status'] = 'not_configured'
                self.warnings.append("Google API not configured")
            else:
                status['status'] = 'configured'

            # Check quota file
            quota_file = os.path.join(project_root, 'data', 'google_api_quota.json')
            if os.path.exists(quota_file):
                with open(quota_file, 'r') as f:
                    quota = json.load(f)
                status['quota'] = quota
                remaining = quota.get('limit', 100) - quota.get('queries_used', 0)
                status['queries_remaining'] = remaining
                if remaining <= 0:
                    self.warnings.append("Google API daily quota exhausted")
                elif remaining <= 10:
                    self.warnings.append(f"Google API quota low: {remaining} remaining")
            else:
                status['quota'] = 'no tracking file'

        except Exception as e:
            status['status'] = 'error'
            status['error'] = str(e)

        self.results['google_api'] = status

    def check_notifications(self):
        """Check notification channels."""
        status = {}
        status['slack'] = 'configured' if settings.slack_webhook_url else 'not_configured'
        status['email'] = 'configured' if settings.smtp_username else 'not_configured'
        if not settings.slack_webhook_url and not settings.smtp_username:
            self.warnings.append("No notification channels configured")
        self.results['notifications'] = status

    def check_pipeline_status(self):
        """Check overall pipeline status."""
        status = {}
        try:
            session = SessionLocal()

            # Products with costs = pipeline ready
            total_products = session.query(Product).filter(Product.status == 'active').count()
            with_costs = session.query(ProductSupplier).filter(ProductSupplier.supplier_cost > 0).count()
            status['products_tracked'] = total_products
            status['products_with_costs'] = with_costs
            status['cost_coverage'] = f"{(with_costs / max(total_products, 1)) * 100:.0f}%"

            # Inventory status
            needs_reorder = session.query(Inventory).filter(Inventory.needs_reorder == True).count()
            status['needs_reorder'] = needs_reorder

            # PO status
            pending_pos = session.query(PurchaseOrder).filter(
                PurchaseOrder.status.in_(['pending', 'confirmed', 'shipped'])
            ).count()
            status['pending_pos'] = pending_pos

            session.close()
        except Exception as e:
            status['error'] = str(e)

        self.results['pipeline'] = status

    def run(self, quick: bool = False):
        """Run all health checks."""
        print("=" * 60)
        print("SYSTEM HEALTH CHECK")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        self.check_database()
        self.check_pipeline_status()

        if not quick:
            self.check_keepa_api()
            self.check_sp_api()
            self.check_google_api()
            self.check_notifications()

        # Print results
        for component, status in self.results.items():
            print(f"\n--- {component.upper()} ---")
            if isinstance(status, dict):
                health = status.get('status', 'n/a')
                icon = {'healthy': '+', 'configured': '+', 'error': 'X',
                        'not_configured': '?', 'unknown': '?'}.get(health, ' ')
                print(f"  [{icon}] Status: {health}")
                for k, v in status.items():
                    if k not in ('status', 'error'):
                        print(f"      {k}: {v}")
                if 'error' in status:
                    print(f"      ERROR: {status['error']}")
            else:
                print(f"  {status}")

        # Summary
        print(f"\n{'=' * 60}")
        if self.errors:
            print(f"ERRORS ({len(self.errors)}):")
            for e in self.errors:
                print(f"  [X] {e}")
        if self.warnings:
            print(f"WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                print(f"  [!] {w}")
        if not self.errors and not self.warnings:
            print("All checks passed!")
        print("=" * 60)

        return len(self.errors) == 0


def main():
    parser = argparse.ArgumentParser(description="System Health Check")
    parser.add_argument("--quick", action="store_true", help="Quick check (DB only, skip API validation)")
    args = parser.parse_args()

    checker = HealthCheck()
    success = checker.run(quick=args.quick)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
