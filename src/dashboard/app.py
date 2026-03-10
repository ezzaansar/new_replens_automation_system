"""
Amazon Replens Automation Dashboard

Provides real-time visibility into system performance and business metrics.

Dashboard Sections (as per Implementation Guide):
1. Overview - Key metrics and KPIs
2. Products - List of tracked products with performance
3. Opportunities - New products awaiting review
4. Inventory - Stock levels and reorder alerts
5. Performance - Charts and trend analysis
6. Settings - Configuration and preferences
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.database import SessionLocal, Product, Supplier, ProductSupplier
from src.api_wrappers.seller_metrics import SellerMetrics
from src.api_wrappers.supplier_metrics import SupplierMetrics
from src.config import settings

# Page configuration
st.set_page_config(
    page_title="Amazon Replens Automation",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize clients
metrics_client = SellerMetrics()
supplier_metrics = SupplierMetrics()

# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

@st.cache_data(ttl=300)
def load_inventory():
    """Load inventory data from Amazon SP-API"""
    try:
        return metrics_client.get_inventory_summary()
    except Exception as e:
        st.error(f"Error loading inventory: {e}")
        return {'total_products': 0, 'total_units': 0, 'inventory_items': []}

@st.cache_data(ttl=300)
def load_orders(days=7):
    """Load orders from Amazon SP-API"""
    try:
        return metrics_client.get_recent_orders(days=days)
    except Exception as e:
        st.error(f"Error loading orders: {e}")
        return {'total_orders': 0, 'total_revenue': 0.0, 'orders': []}

@st.cache_data(ttl=300)
def load_products():
    """Load all products from database"""
    session = SessionLocal()
    try:
        products = session.query(Product).filter(
            Product.status == "active"
        ).order_by(Product.opportunity_score.desc()).all()

        return [{
            'asin': p.asin,
            'title': p.title,
            'opportunity_score': p.opportunity_score,
            'current_price': float(p.current_price),
            'estimated_monthly_sales': p.estimated_monthly_sales,
            'profit_potential': float(p.profit_potential),
            'is_underserved': p.is_underserved,
            'sales_rank': p.sales_rank,
            'num_sellers': p.num_sellers
        } for p in products]
    finally:
        session.close()

@st.cache_data(ttl=300)
def load_opportunities():
    """Load high-opportunity products"""
    session = SessionLocal()
    try:
        products = session.query(Product).filter(
            Product.status == "active",
            Product.is_underserved == True
        ).order_by(Product.opportunity_score.desc()).limit(50).all()

        return [{
            'asin': p.asin,
            'title': p.title,
            'opportunity_score': p.opportunity_score,
            'current_price': float(p.current_price),
            'estimated_monthly_sales': p.estimated_monthly_sales,
            'profit_potential': float(p.profit_potential),
            'sales_rank': p.sales_rank,
            'num_sellers': p.num_sellers
        } for p in products]
    finally:
        session.close()

@st.cache_data(ttl=300)
def load_suppliers():
    """Load supplier data"""
    try:
        return {
            'summary': supplier_metrics.get_supplier_summary(),
            'best_suppliers': supplier_metrics.get_best_suppliers(limit=10),
            'all_suppliers': supplier_metrics.get_all_suppliers(),
            'product_matches': supplier_metrics.get_product_supplier_matches(),
            'products_needing_suppliers': supplier_metrics.get_products_needing_suppliers()
        }
    except Exception as e:
        return {
            'summary': {},
            'best_suppliers': [],
            'all_suppliers': [],
            'product_matches': [],
            'products_needing_suppliers': []
        }

# Load all data
inventory_data = load_inventory()
orders_7d = load_orders(days=7)
orders_30d = load_orders(days=30)
products_data = load_products()
opportunities_data = load_opportunities()
supplier_data = load_suppliers()

# Calculate metrics
def calculate_metrics():
    """Calculate key metrics"""
    revenue_7d = orders_7d.get('total_revenue', 0)
    revenue_30d = orders_30d.get('total_revenue', 0)

    # Extrapolate if needed
    if revenue_30d == 0 and revenue_7d > 0:
        revenue_30d = revenue_7d * 4.3

    return {
        'total_products': len(products_data),
        'opportunities': len(opportunities_data),
        'total_inventory_units': inventory_data.get('total_units', 0),
        'revenue_7d': revenue_7d,
        'revenue_30d': revenue_30d,
        'orders_7d': orders_7d.get('total_orders', 0),
        'orders_30d': orders_30d.get('total_orders', 0),
        'avg_order_value': orders_30d.get('avg_order_value', 0),
        'total_suppliers': supplier_data['summary'].get('total_suppliers', 0),
        'product_matches': supplier_data['summary'].get('total_product_matches', 0),
    }

metrics = calculate_metrics()

# ============================================================================
# SIDEBAR NAVIGATION
# ============================================================================

st.sidebar.title("📊 Amazon Replens")
st.sidebar.markdown("**Automation Dashboard**")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["📈 Overview", "📦 Products", "🎯 Opportunities",
     "📊 Inventory", "📉 Performance", "🧮 Profit Calculator", "⚙️ Settings"]
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Quick Stats")
st.sidebar.metric("Products", metrics['total_products'])
st.sidebar.metric("Opportunities", metrics['opportunities'])
st.sidebar.metric("30-Day Revenue", f"£{metrics['revenue_30d']:,.2f}")

# Refresh button
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ============================================================================
# PAGE 1: OVERVIEW
# ============================================================================

if page == "📈 Overview":
    st.title("📈 Overview")
    st.markdown("**Real-time KPIs and system performance**")
    st.markdown("---")

    # Top-level KPIs
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "30-Day Revenue",
            f"£{metrics['revenue_30d']:,.2f}",
            delta=f"£{metrics['revenue_7d'] * 4.3 - metrics['revenue_30d']:,.2f}" if metrics['revenue_7d'] > 0 else None
        )

    with col2:
        st.metric(
            "Total Products",
            metrics['total_products'],
            delta=f"{metrics['opportunities']} opportunities"
        )

    with col3:
        st.metric(
            "Inventory Units",
            f"{metrics['total_inventory_units']:,}",
            delta="FBA"
        )

    with col4:
        st.metric(
            "Active Suppliers",
            metrics['total_suppliers'],
            delta=f"{metrics['product_matches']} matches"
        )

    st.markdown("---")

    # Secondary metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("7-Day Orders", orders_7d.get('total_orders', 0))
        st.metric("30-Day Orders", orders_30d.get('total_orders', 0))

    with col2:
        st.metric("Avg Order Value", f"£{metrics['avg_order_value']:.2f}")
        turnover = metrics['revenue_30d'] / max(metrics['total_inventory_units'] * 10, 1)
        st.metric("Inventory Turnover", f"{turnover:.1f}x")

    with col3:
        profit_estimate = metrics['revenue_30d'] * 0.25  # Assume 25% margin
        st.metric("Est. 30-Day Profit", f"£{profit_estimate:,.2f}")
        roi = (profit_estimate / max(metrics['total_inventory_units'] * 10, 1)) * 100
        st.metric("Est. ROI", f"{roi:.1f}%")

    st.markdown("---")

    # Recent activity
    st.subheader("Recent Orders")
    if orders_7d.get('orders'):
        df_orders = pd.DataFrame(orders_7d['orders'][:10])
        st.dataframe(df_orders, use_container_width=True)
    else:
        st.info("No recent orders found")

# ============================================================================
# PAGE 2: PRODUCTS
# ============================================================================

elif page == "📦 Products":
    st.title("📦 Products")
    st.markdown("**List of tracked products with performance metrics**")
    st.markdown("---")

    if products_data:
        st.write(f"**Total tracked products: {len(products_data)}**")

        # Create DataFrame
        df = pd.DataFrame(products_data)

        # Format columns
        df['Title'] = df['title']
        df['Price (£)'] = df['current_price'].round(2)
        df['Opp Score'] = df['opportunity_score'].round(1)
        df['Est Monthly Sales'] = df['estimated_monthly_sales']
        df['Profit/Unit (£)'] = df['profit_potential'].round(2)
        df['Sales Rank'] = df['sales_rank']
        df['Sellers'] = df['num_sellers']
        df['Underserved'] = df['is_underserved'].apply(lambda x: '✓' if x else '')

        # Select display columns
        display_df = df[['asin', 'Title', 'Price (£)', 'Opp Score', 'Est Monthly Sales',
                         'Profit/Unit (£)', 'Sales Rank', 'Sellers', 'Underserved']]

        # Display table
        st.dataframe(display_df, use_container_width=True, height=600)

        # Download button
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 Download Product Data (CSV)",
            data=csv,
            file_name=f"products_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No products tracked yet. Run Phase 2 (Product Discovery) to find opportunities.")

# ============================================================================
# PAGE 3: OPPORTUNITIES
# ============================================================================

elif page == "🎯 Opportunities":
    st.title("🎯 Opportunities")
    st.markdown("**High-potential products awaiting review**")
    st.markdown("---")

    if opportunities_data:
        st.write(f"**{len(opportunities_data)} underserved products found**")
        st.markdown("These products have high opportunity scores (low competition, good sales velocity, profitable margins)")

        # Create DataFrame
        df = pd.DataFrame(opportunities_data)

        # Format
        df['Title'] = df['title']
        df['Amazon Link'] = df['asin'].apply(lambda x: f"https://www.amazon.co.uk/dp/{x}")
        df['Price (£)'] = df['current_price'].round(2)
        df['Opp Score'] = df['opportunity_score'].round(1)
        df['Est Monthly Sales'] = df['estimated_monthly_sales']
        df['Profit/Unit (£)'] = df['profit_potential'].round(2)
        df['Monthly Profit Est'] = (df['estimated_monthly_sales'] * df['profit_potential']).round(2)
        df['Sales Rank'] = df['sales_rank']
        df['Sellers'] = df['num_sellers']

        # Display table
        df['Amazon'] = df['asin'].apply(lambda x: f"https://www.amazon.co.uk/dp/{x}")
        display_df = df[['Amazon', 'Title', 'Opp Score', 'Price (£)', 'Est Monthly Sales',
                         'Profit/Unit (£)', 'Monthly Profit Est', 'Sales Rank', 'Sellers']]

        st.dataframe(
            display_df,
            use_container_width=True,
            height=600,
            column_config={
                "Amazon": st.column_config.LinkColumn("Amazon Link")
            }
        )

        # Also show products as individual cards with Amazon links
        st.markdown("---")
        st.subheader("📋 Product Details")

        for _, row in df.iterrows():
            amazon_url = f"https://www.amazon.co.uk/dp/{row['asin']}"
            with st.expander(f"🔹 {row['title'][:80]} — £{row['current_price']:.2f}"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**[View on Amazon UK]({amazon_url})**")
                    st.caption(f"ASIN: {row['asin']}")
                with col2:
                    st.metric("Score", f"{row['opportunity_score']:.0f}/100")

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Price", f"£{row['current_price']:.2f}")
                with col2:
                    st.metric("Monthly Sales", f"{row['estimated_monthly_sales']}")
                with col3:
                    st.metric("Sales Rank", f"{row['sales_rank']:,}" if row['sales_rank'] else "N/A")
                with col4:
                    st.metric("Sellers", f"{row['num_sellers']}")

        # Summary stats
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Avg Opportunity Score", f"{df['opportunity_score'].mean():.1f}/100")

        with col2:
            st.metric("Avg Profit/Unit", f"£{df['profit_potential'].mean():.2f}")

        with col3:
            total_potential = (df['estimated_monthly_sales'] * df['profit_potential']).sum()
            st.metric("Total Monthly Potential", f"£{total_potential:,.2f}")

        with col4:
            st.metric("Avg Competition", f"{df['num_sellers'].mean():.0f} sellers")

    else:
        st.info("No high-opportunity products found yet. Run Phase 2 (Product Discovery) to identify opportunities.")

    # Supplier Links Section - shows ALL products with suppliers (not just opportunities)
    st.markdown("---")
    st.subheader("🔗 Supplier Links")
    st.markdown("Click links to check actual prices, then use the **Profit Calculator** to verify profitability.")

    if supplier_data['product_matches']:
        # Group all matches by ASIN so every product with suppliers is shown
        from collections import defaultdict
        matches_by_asin = defaultdict(list)
        for m in supplier_data['product_matches']:
            matches_by_asin[m['asin']].append(m)

        st.write(f"**{len(matches_by_asin)} products with suppliers found**")

        for asin, product_matches in matches_by_asin.items():
            first_match = product_matches[0]
            product_title = first_match.get('product_title', 'Unknown Product')
            amazon_price = first_match.get('amazon_price', 0)

            with st.expander(f"🔹 {product_title[:80]} — £{amazon_price:.2f}"):
                amazon_url = f"https://www.amazon.co.uk/dp/{asin}"
                st.markdown(f"🛒 **Amazon:** [{product_title[:50]}...]({amazon_url})")
                st.markdown("**Suppliers:**")

                for match in product_matches:
                    supplier_link = match.get('supplier_website') or '#'
                    supplier_name = match.get('supplier_name', 'Unknown')

                    # Determine supplier type from name
                    if any(x in supplier_name for x in ['Alibaba', 'Global Sources', 'Made-in-China', 'DHgate']):
                        badge = "🏭"  # Manufacturer
                    elif any(x in supplier_name for x in ['Wholesale', 'Trade', 'Bulk', 'Costco', 'Makro']):
                        badge = "📦"  # Wholesaler
                    else:
                        badge = "🛒"  # Retailer

                    if supplier_link and supplier_link != '#':
                        st.markdown(f"{badge} [{supplier_name}]({supplier_link})")
                    else:
                        st.markdown(f"{badge} {supplier_name}")

                st.caption(f"Found {len(product_matches)} supplier(s) — Check prices and use Profit Calculator")
    else:
        st.info("No suppliers found. Run Phase 3 (Supplier Matching) to discover suppliers.")

# ============================================================================
# PAGE 4: INVENTORY
# ============================================================================

elif page == "📊 Inventory":
    st.title("📊 Inventory")
    st.markdown("**Stock levels and reorder alerts**")
    st.markdown("---")

    # Summary metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total SKUs", inventory_data.get('total_products', 0))

    with col2:
        st.metric("Total Units", inventory_data.get('total_units', 0))

    with col3:
        fba = inventory_data.get('fba_units', 0)
        st.metric("FBA Units", fba)

    st.markdown("---")

    # Inventory table
    st.subheader("Current Inventory")
    if inventory_data.get('inventory_items'):
        df_inventory = pd.DataFrame(inventory_data['inventory_items'])
        st.dataframe(df_inventory, use_container_width=True, height=500)
    else:
        if 'error' in inventory_data:
            st.error(f"Failed to fetch inventory from Amazon SP-API: {inventory_data.get('error')}")
            if 'error_details' in inventory_data:
                with st.expander("Show error details"):
                    st.code(inventory_data.get('error_details'))
        else:
            st.info("No inventory data available. This may be normal if you have no active listings with stock.")

    st.markdown("---")

    # Reorder alerts (placeholder for Phase 5)
    st.subheader("⚠️ Reorder Alerts")
    st.info("Reorder alerts will be available after implementing Phase 5 (Inventory Forecasting)")

# ============================================================================
# PAGE 5: PERFORMANCE
# ============================================================================

elif page == "📉 Performance":
    st.title("📉 Performance")
    st.markdown("**Charts and trend analysis**")
    st.markdown("---")

    # Revenue trend
    st.subheader("Revenue Trend")
    col1, col2 = st.columns(2)

    with col1:
        st.metric("7-Day Revenue", f"£{metrics['revenue_7d']:,.2f}")

    with col2:
        st.metric("30-Day Revenue", f"£{metrics['revenue_30d']:,.2f}")

    st.info("📊 Historical charts will be available after collecting more data over time")

    st.markdown("---")

    # Product performance
    st.subheader("Top Products by Opportunity Score")
    if products_data:
        top_products = sorted(products_data, key=lambda x: x['opportunity_score'], reverse=True)[:10]
        df_top = pd.DataFrame(top_products)

        chart_data = pd.DataFrame({
            'Product': df_top['title'].str[:30],
            'Opportunity Score': df_top['opportunity_score']
        })

        st.bar_chart(chart_data.set_index('Product'))
    else:
        st.info("No product data available")

    st.markdown("---")

    # Supplier performance
    st.subheader("Supplier Performance")
    if supplier_data['best_suppliers']:
        df_suppliers = pd.DataFrame(supplier_data['best_suppliers'])

        st.write("**Top Suppliers by ROI:**")
        for idx, supplier in enumerate(supplier_data['best_suppliers'][:5], 1):
            supplier_link = supplier.get('website', '#')
            supplier_name = supplier['name']

            if supplier_link and supplier_link != '#':
                st.markdown(f"{idx}. **[{supplier_name}]({supplier_link})** - ROI: {supplier['avg_roi']:.1f}%, "
                           f"Margin: {supplier['avg_profit_margin']:.1f}%, "
                           f"Products: {supplier['product_count']}")
            else:
                st.write(f"{idx}. **{supplier_name}** - ROI: {supplier['avg_roi']:.1f}%, "
                        f"Margin: {supplier['avg_profit_margin']:.1f}%, "
                        f"Products: {supplier['product_count']}")
    else:
        st.info("No supplier data available. Run Phase 3 (Supplier Matching) to find suppliers.")

# ============================================================================
# PAGE 6: PROFIT CALCULATOR
# ============================================================================

elif page == "🧮 Profit Calculator":
    st.title("🧮 Profit Calculator")
    st.markdown("**Calculate FBA profitability with accurate UK fees (effective 15 Dec 2025)**")
    st.markdown("---")

    # ---- FBA Fee Calculation Functions ----

    # UK FBA Fulfilment Fees - Standard (Local/Pan-European, effective 1 Feb 2025)
    UK_FBA_FULFILMENT_FEES = {
        "Light envelope": {
            "dimensions": (33, 23, 2.5),
            "weight_tiers": [
                (0.020, 1.83), (0.040, 1.87), (0.060, 1.89),
                (0.080, 2.07), (0.100, 2.08),
            ]
        },
        "Standard envelope": {
            "dimensions": (33, 23, 2.5),
            "weight_tiers": [(0.210, 2.10), (0.460, 2.16)]
        },
        "Large envelope": {
            "dimensions": (33, 23, 4),
            "weight_tiers": [(0.960, 2.72)]
        },
        "Extra-large envelope": {
            "dimensions": (33, 23, 6),
            "weight_tiers": [(0.960, 2.94)]
        },
        "Small parcel": {
            "dimensions": (35, 25, 12),
            "max_unit_weight": 3.9,
            "max_dim_weight": 2.1,
            "weight_tiers": [
                (0.150, 2.91), (0.400, 3.00), (0.900, 3.04),
                (1.4, 3.05), (1.9, 3.25), (3.9, 3.27),
            ]
        },
        "Standard parcel": {
            "dimensions": (45, 34, 26),
            "max_unit_weight": 11.9,
            "max_dim_weight": 7.96,
            "weight_tiers": [
                (0.150, 2.94), (0.400, 3.01), (0.900, 3.06),
                (1.4, 3.26), (1.9, 3.48), (2.9, 3.49),
                (3.9, 3.54), (5.9, 3.56), (8.9, 3.57), (11.9, 3.58),
            ]
        },
        "Small oversize": {
            "dimensions": (61, 46, 46),
            "max_unit_weight": 1.76,
            "base_fee": 3.65,
            "per_kg_above_760g": 0.25,
        },
        "Standard oversize light": {
            "dimensions": (101, 60, 60),
            "max_unit_weight": 15,
            "base_fee": 4.67,
            "per_kg_above_760g": 0.24,
        },
        "Standard oversize heavy": {
            "dimensions": (101, 60, 60),
            "min_unit_weight": 15,
            "max_unit_weight": 23,
            "base_fee": 8.28,
            "base_weight": 15.76,
            "per_kg_above_base": 0.20,
        },
        "Bulky oversize": {
            "dimensions": (999, 999, 999),  # >120x60x60
            "max_unit_weight": 23,
            "base_fee": 11.53,
            "per_kg_above_760g": 0.31,
        },
        "Heavy oversize": {
            "max_unit_weight": 31.5,
            "base_fee": 13.04,
            "base_weight": 31.5,
            "per_kg_above_base": 0.90,
        },
    }

    # UK FBA Fulfilment Fees - Peak Season (15 Oct 2025 - 14 Jan 2026)
    UK_FBA_PEAK_FEES = {
        "Light envelope": [(0.020, 1.83), (0.040, 1.87), (0.060, 1.89), (0.080, 2.07), (0.100, 2.08)],
        "Standard envelope": [(0.210, 2.10), (0.460, 2.16)],
        "Large envelope": [(0.960, 2.77)],
        "Extra-large envelope": [(0.960, 3.00)],
        "Small parcel": [(0.150, 3.00), (0.400, 3.09), (0.900, 3.13), (1.4, 3.14), (1.9, 3.34), (3.9, 5.25)],
        "Standard parcel": [(0.150, 3.03), (0.400, 3.10), (0.900, 3.15), (1.4, 3.36), (1.9, 3.58),
                           (2.9, 4.87), (3.9, 5.32), (5.9, 5.34), (8.9, 5.74), (11.9, 5.95)],
    }

    # Low-Price FBA Fees (for items <=£10 or <=£20 in most categories)
    UK_LOW_PRICE_FBA_FEES = {
        "Light envelope": [(0.020, 1.46), (0.040, 1.50), (0.060, 1.52), (0.080, 1.67), (0.100, 1.70)],
        "Standard envelope": [(0.210, 1.73), (0.460, 1.87)],
        "Large envelope": [(0.960, 2.42)],
        "Extra-large envelope": [(0.960, 2.65)],
        "Small parcel": [(0.150, 2.67), (0.400, 2.70)],
    }

    # UK Referral Fee Rates by Category
    UK_REFERRAL_FEES = {
        "Amazon Device Accessories": {"rate": 0.45},
        "Automotive and Powersports": {"rate": 0.15, "threshold": 45.0, "rate_above": 0.09},
        "Baby Products": {"rate_below_10": 0.08, "rate_above_10": 0.15},
        "Beauty, Health and Personal Care": {"rate_below_10": 0.08, "rate_above_10": 0.15},
        "Beer, Wine and Spirits": {"rate": 0.10},
        "Books": {"rate": 0.15, "closing_fee": 0.50},
        "Business, Industrial and Scientific": {"rate": 0.15},
        "Clothing and Accessories": {"rate_below_15": 0.05, "rate_15_to_20": 0.10, "rate_above_20": 0.15,
                                     "fba_threshold": 40.0, "rate_above_fba_threshold": 0.07},
        "Compact Appliances": {"rate": 0.15},
        "Computers": {"rate": 0.07},
        "Consumer Electronics": {"rate": 0.07},
        "Electronic Accessories": {"rate": 0.15, "threshold": 100.0, "rate_above": 0.08},
        "Eyewear": {"rate": 0.15},
        "Footwear": {"rate": 0.15},
        "Full-Size Appliances": {"rate": 0.07},
        "Furniture": {"rate": 0.15, "threshold": 175.0, "rate_above": 0.10},
        "Furniture Accessories": {"rate": 0.13},
        "Grocery and Gourmet": {"rate_below_10": 0.05, "rate_above_10": 0.15},
        "Handmade": {"rate": 0.12},
        "Home Products": {"rate_below_20": 0.08, "rate_above_20": 0.15},
        "Jewellery": {"rate": 0.20, "threshold": 225.0, "rate_above": 0.05},
        "Kitchen": {"rate": 0.15},
        "Lawn and Garden": {"rate": 0.15},
        "Luggage": {"rate": 0.15},
        "Mattresses": {"rate": 0.15},
        "Music, Video and DVD": {"rate": 0.15, "closing_fee": 0.50},
        "Musical Instruments": {"rate": 0.12},
        "Office Products": {"rate": 0.15},
        "Pet Supplies": {"rate": 0.15},
        "Pet Clothing and Food": {"rate_below_10": 0.05, "rate_above_10": 0.15},
        "Software": {"rate": 0.15, "closing_fee": 0.50},
        "Sports and Outdoors": {"rate": 0.15},
        "Tools and Home Improvement": {"rate": 0.13},
        "Toys and Games": {"rate": 0.15},
        "Tyres": {"rate": 0.07},
        "Video Games and Gaming Accessories": {"rate": 0.15, "closing_fee": 0.50},
        "Video Game Consoles": {"rate": 0.08},
        "Vitamins, Minerals & Supplements": {"rate_below_10": 0.05, "rate_above_10": 0.15},
        "Watches": {"rate": 0.15, "threshold": 225.0, "rate_above": 0.05},
        "Everything else": {"rate": 0.15},
    }

    # UK Monthly Storage Fees (£ per cubic foot per month)
    UK_STORAGE_FEES = {
        "standard": {"jan_sep": 0.76, "oct_dec": 1.37},
        "standard_clothing": {"jan_sep": 0.56, "oct_dec": 0.75},
        "oversize": {"jan_sep": 0.50, "oct_dec": 0.79},
    }

    def determine_size_tier(length_cm, width_cm, height_cm, weight_kg):
        """Determine the FBA size tier based on dimensions and weight."""
        dims = sorted([length_cm, width_cm, height_cm], reverse=True)
        l, w, h = dims

        if l <= 33 and w <= 23 and h <= 2.5 and weight_kg <= 0.460:
            if weight_kg <= 0.100:
                return "Light envelope"
            else:
                return "Standard envelope"
        elif l <= 33 and w <= 23 and h <= 4 and weight_kg <= 0.960:
            return "Large envelope"
        elif l <= 33 and w <= 23 and h <= 6 and weight_kg <= 0.960:
            return "Extra-large envelope"
        elif l <= 35 and w <= 25 and h <= 12 and weight_kg <= 3.9:
            return "Small parcel"
        elif l <= 45 and w <= 34 and h <= 26 and weight_kg <= 11.9:
            return "Standard parcel"
        elif l <= 61 and w <= 46 and h <= 46 and weight_kg <= 1.76:
            return "Small oversize"
        elif l <= 101 and w <= 60 and h <= 60 and weight_kg <= 15:
            return "Standard oversize light"
        elif l <= 101 and w <= 60 and h <= 60 and weight_kg <= 23:
            return "Standard oversize heavy"
        elif l <= 120 and w <= 60 and h <= 60 and weight_kg <= 23:
            return "Standard oversize large"
        elif weight_kg <= 23:
            return "Bulky oversize"
        elif weight_kg <= 31.5:
            return "Heavy oversize"
        else:
            return "Special oversize"

    def calculate_dimensional_weight(length_cm, width_cm, height_cm):
        """Calculate dimensional weight in kg: (L x W x H) / 5000"""
        return (length_cm * width_cm * height_cm) / 5000

    def get_shipping_weight(size_tier, unit_weight_kg, dim_weight_kg):
        """Determine shipping weight based on size tier rules."""
        # Envelopes and special oversize use unit weight
        if "envelope" in size_tier.lower() or size_tier == "Special oversize":
            return unit_weight_kg
        # Parcels and oversize use the greater of unit weight or dimensional weight
        return max(unit_weight_kg, dim_weight_kg)

    def calculate_fulfilment_fee(size_tier, shipping_weight_kg, is_peak=False, is_low_price=False):
        """Calculate the UK FBA fulfilment fee based on size tier and weight."""
        if is_low_price and size_tier in UK_LOW_PRICE_FBA_FEES:
            weight_tiers = UK_LOW_PRICE_FBA_FEES[size_tier]
            for max_weight, fee in weight_tiers:
                if shipping_weight_kg <= max_weight:
                    return fee
            return weight_tiers[-1][1]

        if is_peak and size_tier in UK_FBA_PEAK_FEES:
            weight_tiers = UK_FBA_PEAK_FEES[size_tier]
            for max_weight, fee in weight_tiers:
                if shipping_weight_kg <= max_weight:
                    return fee
            return weight_tiers[-1][1]

        tier_data = UK_FBA_FULFILMENT_FEES.get(size_tier)
        if not tier_data:
            return 3.58  # Default to max standard parcel fee

        # Oversize tiers with base_fee + per_kg
        if "base_fee" in tier_data:
            base_fee = tier_data["base_fee"]
            if "per_kg_above_760g" in tier_data:
                if shipping_weight_kg > 0.760:
                    return base_fee + (shipping_weight_kg - 0.760) * tier_data["per_kg_above_760g"]
                return base_fee
            elif "per_kg_above_base" in tier_data:
                base_weight = tier_data["base_weight"]
                if shipping_weight_kg > base_weight:
                    return base_fee + (shipping_weight_kg - base_weight) * tier_data["per_kg_above_base"]
                return base_fee

        # Standard tiers with weight_tiers list
        weight_tiers = tier_data.get("weight_tiers", [])
        for max_weight, fee in weight_tiers:
            if shipping_weight_kg <= max_weight:
                return fee

        # If weight exceeds all tiers, return last tier fee
        if weight_tiers:
            return weight_tiers[-1][1]
        return 3.58

    def calculate_referral_fee(category, price):
        """Calculate UK referral fee based on category and price."""
        min_fee = 0.25
        fee_config = UK_REFERRAL_FEES.get(category, UK_REFERRAL_FEES["Everything else"])

        if "rate_below_10" in fee_config:
            if price <= 10:
                fee = price * fee_config["rate_below_10"]
            else:
                fee = price * fee_config["rate_above_10"]
        elif "rate_below_15" in fee_config:
            # Clothing-style tiered
            if price <= 15:
                fee = price * fee_config["rate_below_15"]
            elif price <= 20:
                fee = price * fee_config["rate_15_to_20"]
            else:
                fba_threshold = fee_config.get("fba_threshold", 999)
                if price > fba_threshold:
                    fee = fba_threshold * fee_config["rate_above_20"] + \
                          (price - fba_threshold) * fee_config.get("rate_above_fba_threshold", fee_config["rate_above_20"])
                else:
                    fee = price * fee_config["rate_above_20"]
        elif "rate_below_20" in fee_config:
            if price <= 20:
                fee = price * fee_config["rate_below_20"]
            else:
                fee = price * fee_config["rate_above_20"]
        elif "threshold" in fee_config:
            threshold = fee_config["threshold"]
            if price <= threshold:
                fee = price * fee_config["rate"]
            else:
                fee = threshold * fee_config["rate"] + (price - threshold) * fee_config["rate_above"]
        else:
            fee = price * fee_config["rate"]

        closing_fee = fee_config.get("closing_fee", 0)
        return max(fee, min_fee) + closing_fee

    def calculate_monthly_storage_fee(length_cm, width_cm, height_cm, is_oversize=False, is_clothing=False, month=None):
        """Calculate monthly storage fee per unit in £."""
        import calendar
        if month is None:
            month = datetime.now().month

        # Volume in cubic feet (1 cubic foot = 28316.8 cm³)
        volume_cm3 = length_cm * width_cm * height_cm
        volume_ft3 = volume_cm3 / 28316.8

        if is_oversize:
            rate = UK_STORAGE_FEES["oversize"]
        elif is_clothing:
            rate = UK_STORAGE_FEES["standard_clothing"]
        else:
            rate = UK_STORAGE_FEES["standard"]

        if month >= 10 or month <= 12:  # Oct-Dec
            fee_per_ft3 = rate["oct_dec"]
        else:  # Jan-Sep
            fee_per_ft3 = rate["jan_sep"]

        return volume_ft3 * fee_per_ft3

    # ---- UI ----
    calc_col, saved_col = st.columns([2, 1])

    with calc_col:
        st.subheader("Calculate Profit")

        # Product selection or manual entry
        calc_mode = st.radio("Mode", ["Select Product", "Manual Entry"], horizontal=True)

        if calc_mode == "Select Product":
            session = SessionLocal()
            try:
                products_with_suppliers = session.query(Product).join(
                    ProductSupplier, Product.asin == ProductSupplier.asin
                ).distinct().all()

                if products_with_suppliers:
                    product_options = {f"{p.title[:60]}... (£{p.current_price})": p for p in products_with_suppliers}
                    selected_product_name = st.selectbox("Select Product", list(product_options.keys()))
                    selected_product = product_options[selected_product_name]

                    amazon_price = float(selected_product.current_price)
                    st.info(f"**Amazon Price:** £{amazon_price:.2f}")

                    linked_suppliers = session.query(Supplier).join(
                        ProductSupplier, Supplier.supplier_id == ProductSupplier.supplier_id
                    ).filter(ProductSupplier.asin == selected_product.asin).all()

                    if linked_suppliers:
                        st.markdown("**Linked Suppliers:**")
                        for sup in linked_suppliers:
                            st.markdown(f"- [{sup.name}]({sup.website})")
                else:
                    st.warning("No products with suppliers found. Run Phase 3 first.")
                    amazon_price = 10.00
                    selected_product = None
            finally:
                session.close()
        else:
            amazon_price = st.number_input("Amazon Selling Price (£)", min_value=0.01, value=10.00, step=0.01)
            selected_product = None

        st.markdown("---")

        # Product dimensions and weight
        st.markdown("**Product Dimensions & Weight:**")
        dim_col1, dim_col2, dim_col3, dim_col4 = st.columns(4)
        with dim_col1:
            prod_length = st.number_input("Length (cm)", min_value=0.1, value=20.0, step=0.1)
        with dim_col2:
            prod_width = st.number_input("Width (cm)", min_value=0.1, value=15.0, step=0.1)
        with dim_col3:
            prod_height = st.number_input("Height (cm)", min_value=0.1, value=5.0, step=0.1)
        with dim_col4:
            prod_weight = st.number_input("Weight (kg)", min_value=0.001, value=0.300, step=0.01)

        # Category selection
        category = st.selectbox("Product Category", list(UK_REFERRAL_FEES.keys()),
                               index=list(UK_REFERRAL_FEES.keys()).index("Everything else"))

        # Fee options
        opt_col1, opt_col2, opt_col3 = st.columns(3)
        with opt_col1:
            is_peak = st.checkbox("Peak season (15 Oct - 14 Jan)", value=False)
        with opt_col2:
            is_low_price = st.checkbox("Low-Price FBA eligible", value=False,
                                       help="Items priced <=£10 (all cats) or <=£20 (most cats)")
        with opt_col3:
            has_lithium_battery = st.checkbox("Lithium battery / Hazmat", value=False,
                                             help="Additional £0.10 per unit")

        st.markdown("---")

        # Cost inputs
        st.markdown("**Supplier & Shipping Costs:**")
        col1, col2 = st.columns(2)
        with col1:
            supplier_cost = st.number_input("Supplier Cost per Unit (£)", min_value=0.0, value=0.0, step=0.01,
                                           help="Price you pay to the supplier per unit")
        with col2:
            shipping_to_fba = st.number_input("Shipping to FBA per Unit (£)", min_value=0.0, value=0.0, step=0.01,
                                              help="Cost to get the item to Amazon's warehouse")

        with st.expander("Additional Costs (Optional)"):
            add_col1, add_col2, add_col3 = st.columns(3)
            with add_col1:
                packaging_cost = st.number_input("Packaging Cost (£)", min_value=0.0, value=0.0, step=0.01)
            with add_col2:
                prep_cost = st.number_input("FBA Prep Cost (£)", min_value=0.0, value=0.0, step=0.01,
                                           help="Label: £0.78, Bag: £0.75, Bubble wrap: £1.00 per parcel")
            with add_col3:
                other_costs = st.number_input("Other Costs (£)", min_value=0.0, value=0.0, step=0.01)
            vat_registered = st.checkbox("VAT registered (can reclaim input VAT)", value=False)
            avg_storage_months = st.number_input("Avg months in storage", min_value=0.0, value=1.0, step=0.5,
                                                 help="How long the product sits in Amazon's warehouse")

        st.markdown("---")

        # Calculate button
        if st.button("Calculate Profit", type="primary"):
            if supplier_cost == 0:
                st.warning("Please enter a supplier cost")
            else:
                # Determine size tier
                size_tier = determine_size_tier(prod_length, prod_width, prod_height, prod_weight)
                dim_weight = calculate_dimensional_weight(prod_length, prod_width, prod_height)
                shipping_weight = get_shipping_weight(size_tier, prod_weight, dim_weight)
                is_oversize = "oversize" in size_tier.lower()

                # Calculate FBA fulfilment fee
                fulfilment_fee = calculate_fulfilment_fee(size_tier, shipping_weight, is_peak, is_low_price)

                # Lithium battery surcharge
                battery_fee = 0.10 if has_lithium_battery else 0.0

                # Calculate referral fee
                referral_fee = calculate_referral_fee(category, amazon_price)

                # Calculate storage fee
                storage_fee = calculate_monthly_storage_fee(
                    prod_length, prod_width, prod_height,
                    is_oversize=is_oversize
                ) * avg_storage_months

                # VAT considerations
                vat_on_fees = 0.0
                if not vat_registered:
                    # Non-VAT registered sellers can't reclaim VAT on Amazon fees
                    vat_on_fees = (fulfilment_fee + storage_fee) * 0.20

                # Total Amazon fees
                total_amazon_fees = fulfilment_fee + referral_fee + storage_fee + battery_fee + vat_on_fees

                # Total product costs
                total_product_cost = supplier_cost + shipping_to_fba + packaging_cost + prep_cost + other_costs

                # Total costs
                total_cost = total_product_cost + total_amazon_fees

                # Profit calculations
                profit = amazon_price - total_cost
                profit_margin = (profit / amazon_price) * 100 if amazon_price > 0 else 0
                roi = (profit / total_product_cost) * 100 if total_product_cost > 0 else 0

                # Display results
                st.markdown("### Results")

                if profit > 0:
                    st.success(f"### Profit: £{profit:.2f} per unit")
                else:
                    st.error(f"### Loss: £{abs(profit):.2f} per unit")

                result_col1, result_col2, result_col3, result_col4 = st.columns(4)
                with result_col1:
                    st.metric("Profit Margin", f"{profit_margin:.1f}%",
                             delta="Good" if profit_margin >= 15 else ("OK" if profit_margin >= 5 else "Low"))
                with result_col2:
                    st.metric("ROI", f"{roi:.1f}%",
                             delta="Good" if roi >= 30 else ("OK" if roi >= 10 else "Low"))
                with result_col3:
                    st.metric("Profit per Unit", f"£{profit:.2f}")
                with result_col4:
                    st.metric("Size Tier", size_tier)

                # Detailed cost breakdown
                st.markdown("### Cost Breakdown")

                breakdown_data = {
                    "Item": [
                        "Amazon Selling Price",
                        "---",
                        "Supplier Cost",
                        "Shipping to FBA",
                        "Packaging",
                        "FBA Prep",
                        "Other Costs",
                        "Subtotal: Product Costs",
                        "---",
                        f"FBA Fulfilment Fee ({size_tier}, {shipping_weight:.2f}kg)",
                        f"Referral Fee ({category})",
                        f"Storage Fee ({avg_storage_months:.1f} months)",
                        "Lithium/Hazmat Surcharge" if has_lithium_battery else "Lithium/Hazmat Surcharge",
                        "VAT on fees (non-registered)" if not vat_registered else "VAT on fees",
                        "Subtotal: Amazon Fees",
                        "---",
                        "TOTAL COSTS",
                        "PROFIT",
                    ],
                    "Amount (£)": [
                        f"{amazon_price:.2f}",
                        "---",
                        f"{supplier_cost:.2f}",
                        f"{shipping_to_fba:.2f}",
                        f"{packaging_cost:.2f}",
                        f"{prep_cost:.2f}",
                        f"{other_costs:.2f}",
                        f"{total_product_cost:.2f}",
                        "---",
                        f"{fulfilment_fee:.2f}",
                        f"{referral_fee:.2f}",
                        f"{storage_fee:.2f}",
                        f"{battery_fee:.2f}",
                        f"{vat_on_fees:.2f}",
                        f"{total_amazon_fees:.2f}",
                        "---",
                        f"{total_cost:.2f}",
                        f"{profit:.2f}",
                    ]
                }
                st.table(pd.DataFrame(breakdown_data))

                # Additional info
                st.markdown("### Fee Details")
                st.caption(f"Dimensional weight: {dim_weight:.3f} kg | "
                          f"Shipping weight used: {shipping_weight:.3f} kg | "
                          f"Peak season: {'Yes' if is_peak else 'No'} | "
                          f"Low-Price FBA: {'Yes' if is_low_price else 'No'}")

                # Recommendation
                st.markdown("### Recommendation")
                if profit_margin >= 20:
                    st.success("**Excellent opportunity!** High profit margin. Consider sourcing this product.")
                elif profit_margin >= 10:
                    st.info("**Good opportunity.** Decent margin. Worth considering if volume is good.")
                elif profit_margin >= 5:
                    st.warning("**Marginal.** Low margin. Only viable with high volume or lower costs.")
                elif profit > 0:
                    st.warning("**Risky.** Very low margin. Look for better pricing or skip.")
                else:
                    st.error("**Not profitable.** Find a cheaper supplier or skip this product.")

                # Save option
                if selected_product and calc_mode == "Select Product":
                    st.markdown("---")
                    if st.button("Save These Costs to Database"):
                        session = SessionLocal()
                        try:
                            matches = session.query(ProductSupplier).filter(
                                ProductSupplier.asin == selected_product.asin
                            ).all()

                            for match in matches:
                                match.supplier_cost = supplier_cost
                                match.shipping_cost = shipping_to_fba
                                match.total_cost = total_product_cost
                                match.estimated_profit = profit
                                match.profit_margin = profit_margin / 100
                                match.roi = roi / 100

                            session.commit()
                            st.success(f"Saved costs for {len(matches)} supplier match(es)")
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Error saving: {e}")
                        finally:
                            session.close()

    with saved_col:
        st.subheader("UK FBA Fee Reference")
        st.caption("Effective 15 Dec 2025")

        st.markdown("**Fulfilment Fees (standard):**")
        st.markdown("""
| Size Tier | Fee |
|-----------|-----|
| Light envelope | £1.83-2.08 |
| Std envelope | £2.10-2.16 |
| Large envelope | £2.72 |
| Small parcel | £2.91-3.27 |
| Std parcel | £2.94-3.58 |
| Small oversize | £3.65+ |
| Std oversize | £4.67+ |
| Bulky oversize | £11.53+ |
        """)

        st.markdown("---")

        st.markdown("**Monthly Storage (£/ft³):**")
        st.markdown("""
| Period | Std | Oversize |
|--------|-----|----------|
| Jan-Sep | £0.76 | £0.50 |
| Oct-Dec | £1.37 | £0.79 |
        """)

        st.markdown("---")

        st.markdown("**Referral Fees (common):**")
        st.markdown("""
- Most categories: **15%**
- Electronics: **7%**
- Clothing: **5-15%** (tiered)
- Furniture: **15%**/10% above £175
- Grocery: **5%**/15% above £10
- Tools: **13%**
- Min fee: **£0.25**
        """)

        st.markdown("---")

        st.markdown("**Aged Inventory Surcharge:**")
        st.markdown("""
| Days | £/ft³/month |
|------|-------------|
| 241-270 | £1.18 |
| 271-365 | £3.14-3.41 |
| 365+ | £5.71 |
        """)

        st.markdown("---")

        st.markdown("**Storage Utilization Surcharge:**")
        st.markdown("""
Applies if ratio > 22 weeks:
- 22-28 wks: +£0.42/ft³
- 28-36 wks: +£0.78/ft³
- 36-52 wks: +£1.04-1.41/ft³
- 52+ wks: +£2.29/ft³
        """)

        st.markdown("---")

        st.markdown("**Additional fees:**")
        st.markdown("""
- Lithium/Hazmat: +£0.10/unit
- FBA Prep (label): £0.78
- FBA Prep (bag): £0.75
- FBA Prep (bubble): £1.00
- Manual processing: £0.15
        """)

# ============================================================================
# PAGE 7: SETTINGS
# ============================================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")
    st.markdown("**Configuration and preferences**")
    st.markdown("---")

    st.subheader("System Configuration")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**📦 Amazon Configuration**")
        st.text(f"Region: {settings.amazon_region}")
        st.text(f"Seller ID: {settings.amazon_seller_id[:8]}...")
        st.text(f"Keepa Domain: {settings.keepa_domain}")

    with col2:
        st.markdown("**💰 Profitability Thresholds**")
        st.text(f"Min Profit Margin: {settings.min_profit_margin * 100:.0f}%")
        st.text(f"Min ROI: {settings.min_roi * 100:.0f}%")
        st.text(f"Min Sales Velocity: {settings.min_sales_velocity} units/month")

    st.markdown("---")

    st.subheader("Repricing Configuration")

    col1, col2 = st.columns(2)

    with col1:
        st.text(f"Target Buy Box Win Rate: {settings.target_buy_box_win_rate * 100:.0f}%")
        st.text(f"Price Adjustment Amount: £{settings.price_adjustment_amount}")

    with col2:
        st.text(f"Max Price Multiplier: {settings.max_price_multiplier}x")
        st.text(f"Min Price Change: {settings.min_price_change_percent * 100:.0f}%")

    st.markdown("---")

    st.subheader("System Actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔍 Run Product Discovery"):
            st.info("Run: `uv run python -m src.phases.phase_2_auto_discovery`")

    with col2:
        if st.button("🏭 Run Supplier Matching"):
            st.info("Run: `uv run python -m src.phases.phase_3_sourcing_with_openai`")

    with col3:
        if st.button("💲 Run Repricing"):
            st.info("Run: `uv run python -m src.phases.phase_4_repricing`")

    st.markdown("---")

    st.subheader("Database Information")
    session = SessionLocal()
    try:
        product_count = session.query(Product).count()
        supplier_count = session.query(Supplier).count()
        match_count = session.query(ProductSupplier).count()

        st.text(f"Products in database: {product_count}")
        st.text(f"Suppliers in database: {supplier_count}")
        st.text(f"Product-Supplier matches: {match_count}")
    finally:
        session.close()

# ============================================================================
# FOOTER
# ============================================================================

st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666;'>
    Amazon Replens Automation System v1.0 |
    Last updated: {} |
    <a href='https://github.com/yourusername/replens-automation'>Documentation</a>
    </div>
    """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    unsafe_allow_html=True
)
