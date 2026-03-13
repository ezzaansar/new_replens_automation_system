"""
Export products from the database to a CSV file for sharing with clients.
Includes product details, pricing, supplier costs, and profitability metrics.
"""

import csv
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import DatabaseOperations, Product, ProductSupplier, Supplier


def export_products_csv(output_path=None):
    """Export all active products to a client-ready CSV file."""
    if output_path is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', f'products_for_client_{timestamp}.csv'
        )

    db = DatabaseOperations()
    session = db.get_session()

    try:
        # Query products with supplier info
        products = (
            session.query(Product)
            .filter(Product.status == 'active')
            .order_by(Product.opportunity_score.desc())
            .all()
        )

        if not products:
            print("No active products found in database.")
            return

        # Build rows with supplier data
        rows = []
        for p in products:
            # Get preferred/best supplier for this product
            supplier_link = (
                session.query(ProductSupplier, Supplier)
                .join(Supplier, ProductSupplier.supplier_id == Supplier.supplier_id)
                .filter(ProductSupplier.asin == p.asin)
                .order_by(ProductSupplier.is_preferred.desc(), ProductSupplier.profit_margin.desc())
                .first()
            )

            supplier_cost = ''
            shipping_cost = ''
            total_cost = ''
            estimated_profit = ''
            profit_margin = ''
            roi = ''
            supplier_name = ''

            if supplier_link:
                ps, sup = supplier_link
                supplier_cost = f"{ps.supplier_cost:.2f}" if ps.supplier_cost else ''
                shipping_cost = f"{ps.shipping_cost:.2f}" if ps.shipping_cost else ''
                total_cost = f"{ps.total_cost:.2f}" if ps.total_cost else ''
                estimated_profit = f"{ps.estimated_profit:.2f}" if ps.estimated_profit else ''
                profit_margin = f"{ps.profit_margin:.1f}" if ps.profit_margin else ''
                roi = f"{ps.roi:.1f}" if ps.roi else ''
                supplier_name = sup.name if sup.name else ''

            rows.append({
                'ASIN': p.asin,
                'UPC': p.upc or '',
                'Title': p.title,
                'Category': p.category,
                'Amazon Price (£)': f"{p.current_price:.2f}" if p.current_price else '',
                'Sales Rank': p.sales_rank or '',
                'Est. Monthly Sales': p.estimated_monthly_sales or '',
                'Opportunity Score': f"{p.opportunity_score:.1f}" if p.opportunity_score else '',
                'Num Sellers': p.num_sellers or '',
                'Num FBA Sellers': p.num_fba_sellers or '',
                'Buy Box Owner': p.buy_box_owner or '',
                'Avg Price (90d) (£)': f"{p.price_history_avg:.2f}" if p.price_history_avg else '',
                'Price Stability': f"{p.price_stability:.2f}" if p.price_stability else '',
                'Underserved': 'Yes' if p.is_underserved else 'No',
                'Supplier Name': supplier_name,
                'Supplier Cost (£)': supplier_cost,
                'Shipping Cost (£)': shipping_cost,
                'Total Cost (£)': total_cost,
                'Est. Profit/Unit (£)': estimated_profit,
                'Profit Margin (%)': profit_margin,
                'ROI (%)': roi,
                'Profit Potential (£)': f"{p.profit_potential:.2f}" if p.profit_potential else '',
                'Notes': p.notes or '',
            })

        # Write CSV
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        fieldnames = rows[0].keys()

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"Exported {len(rows)} products to: {os.path.abspath(output_path)}")
        return output_path

    finally:
        session.close()


if __name__ == '__main__':
    custom_path = sys.argv[1] if len(sys.argv) > 1 else None
    export_products_csv(custom_path)
