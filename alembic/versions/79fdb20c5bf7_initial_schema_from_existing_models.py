"""Initial schema from existing models

Revision ID: 79fdb20c5bf7
Revises:
Create Date: 2026-03-13 01:30:45.028373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79fdb20c5bf7'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial schema."""
    op.create_table(
        'products',
        sa.Column('asin', sa.String(10), primary_key=True),
        sa.Column('upc', sa.String(14), nullable=True),
        sa.Column('title', sa.String(500)),
        sa.Column('category', sa.String(200)),
        sa.Column('current_price', sa.Numeric(10, 2)),
        sa.Column('sales_rank', sa.Integer, nullable=True),
        sa.Column('estimated_monthly_sales', sa.Integer, default=0),
        sa.Column('profit_potential', sa.Numeric(10, 2), default=0),
        sa.Column('num_sellers', sa.Integer, default=0),
        sa.Column('num_fba_sellers', sa.Integer, default=0),
        sa.Column('buy_box_owner', sa.String(200), nullable=True),
        sa.Column('price_history_avg', sa.Numeric(10, 2), nullable=True),
        sa.Column('price_stability', sa.Numeric(10, 2), nullable=True),
        sa.Column('is_underserved', sa.Boolean, default=False),
        sa.Column('opportunity_score', sa.Float, default=0.0),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime),
        sa.Column('last_updated', sa.DateTime),
    )
    op.create_index('ix_products_asin', 'products', ['asin'])
    op.create_index('ix_products_upc', 'products', ['upc'])
    op.create_index('ix_products_is_underserved', 'products', ['is_underserved'])
    op.create_index('ix_products_status', 'products', ['status'])
    op.create_index('idx_status_score', 'products', ['status', 'opportunity_score'])
    op.create_index('idx_underserved', 'products', ['is_underserved'])

    op.create_table(
        'suppliers',
        sa.Column('supplier_id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(200), unique=True),
        sa.Column('website', sa.String(500), nullable=True),
        sa.Column('contact_email', sa.String(200), nullable=True),
        sa.Column('min_order_qty', sa.Integer, default=1),
        sa.Column('lead_time_days', sa.Integer, default=7),
        sa.Column('reliability_score', sa.Float, default=0.0),
        sa.Column('last_order_date', sa.DateTime, nullable=True),
        sa.Column('total_orders', sa.Integer, default=0),
        sa.Column('on_time_delivery_rate', sa.Float, default=1.0),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime),
        sa.Column('last_updated', sa.DateTime),
    )
    op.create_index('ix_suppliers_name', 'suppliers', ['name'])
    op.create_index('ix_suppliers_status', 'suppliers', ['status'])

    op.create_table(
        'product_suppliers',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('asin', sa.String(10), sa.ForeignKey('products.asin')),
        sa.Column('supplier_id', sa.Integer, sa.ForeignKey('suppliers.supplier_id')),
        sa.Column('supplier_cost', sa.Numeric(10, 2)),
        sa.Column('shipping_cost', sa.Numeric(10, 2), default=0),
        sa.Column('total_cost', sa.Numeric(10, 2)),
        sa.Column('estimated_profit', sa.Numeric(10, 2)),
        sa.Column('profit_margin', sa.Float),
        sa.Column('roi', sa.Float),
        sa.Column('is_preferred', sa.Boolean, default=False),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('created_at', sa.DateTime),
        sa.Column('last_updated', sa.DateTime),
    )
    op.create_index('ix_product_suppliers_asin', 'product_suppliers', ['asin'])
    op.create_index('ix_product_suppliers_supplier_id', 'product_suppliers', ['supplier_id'])

    op.create_table(
        'inventory',
        sa.Column('asin', sa.String(10), sa.ForeignKey('products.asin'), primary_key=True),
        sa.Column('current_stock', sa.Integer, default=0),
        sa.Column('reserved', sa.Integer, default=0),
        sa.Column('available', sa.Integer, default=0),
        sa.Column('reorder_point', sa.Integer, default=0),
        sa.Column('safety_stock', sa.Integer, default=0),
        sa.Column('forecasted_stock_30d', sa.Integer, nullable=True),
        sa.Column('forecasted_stock_60d', sa.Integer, nullable=True),
        sa.Column('last_restock_date', sa.DateTime, nullable=True),
        sa.Column('days_of_supply', sa.Float, default=0),
        sa.Column('needs_reorder', sa.Boolean, default=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('last_updated', sa.DateTime),
    )
    op.create_index('ix_inventory_needs_reorder', 'inventory', ['needs_reorder'])

    op.create_table(
        'purchase_orders',
        sa.Column('po_id', sa.String(50), primary_key=True),
        sa.Column('asin', sa.String(10), sa.ForeignKey('products.asin')),
        sa.Column('supplier_id', sa.Integer, sa.ForeignKey('suppliers.supplier_id')),
        sa.Column('quantity', sa.Integer),
        sa.Column('unit_cost', sa.Numeric(10, 2)),
        sa.Column('total_cost', sa.Numeric(10, 2)),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('order_date', sa.DateTime),
        sa.Column('expected_delivery', sa.DateTime, nullable=True),
        sa.Column('actual_delivery', sa.DateTime, nullable=True),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime),
        sa.Column('last_updated', sa.DateTime),
    )
    op.create_index('ix_purchase_orders_po_id', 'purchase_orders', ['po_id'])
    op.create_index('ix_purchase_orders_asin', 'purchase_orders', ['asin'])
    op.create_index('ix_purchase_orders_supplier_id', 'purchase_orders', ['supplier_id'])
    op.create_index('ix_purchase_orders_status', 'purchase_orders', ['status'])

    op.create_table(
        'performance',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('asin', sa.String(10), sa.ForeignKey('products.asin')),
        sa.Column('date', sa.DateTime),
        sa.Column('units_sold', sa.Integer, default=0),
        sa.Column('revenue', sa.Numeric(10, 2), default=0),
        sa.Column('cost_of_goods', sa.Numeric(10, 2), default=0),
        sa.Column('amazon_fees', sa.Numeric(10, 2), default=0),
        sa.Column('net_profit', sa.Numeric(10, 2), default=0),
        sa.Column('buy_box_owned', sa.Boolean, default=False),
        sa.Column('buy_box_percentage', sa.Float, default=0.0),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('competitor_price', sa.Numeric(10, 2), nullable=True),
        sa.Column('sales_rank', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime),
    )
    op.create_index('ix_performance_asin', 'performance', ['asin'])
    op.create_index('ix_performance_date', 'performance', ['date'])
    op.create_index('idx_asin_date', 'performance', ['asin', 'date'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('performance')
    op.drop_table('purchase_orders')
    op.drop_table('inventory')
    op.drop_table('product_suppliers')
    op.drop_table('suppliers')
    op.drop_table('products')
