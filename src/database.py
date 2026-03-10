"""
Database Models and Operations for Amazon Replens Automation System

Defines SQLAlchemy ORM models for all core entities:
- Products (ASINs with metrics)
- Suppliers (sourcing partners)
- Inventory (stock levels and forecasts)
- Purchase Orders (procurement tracking)
- Performance Metrics (KPIs and analytics)
"""

from datetime import datetime
from typing import Optional, List
from decimal import Decimal

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Boolean, ForeignKey, Numeric, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

load_dotenv()

# Database Configuration
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./replens_automation.db")

# Create engine based on database type
if DATABASE_TYPE == "sqlite":
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
else:  # PostgreSQL
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        echo=False
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============================================================================
# PRODUCT MODEL
# ============================================================================
class Product(Base):
    """
    Represents an Amazon product (ASIN) being tracked for Replens opportunities.
    
    Attributes:
        asin: Amazon Standard Identification Number (primary key)
        upc: Universal Product Code
        title: Product title
        category: Amazon category
        current_price: Current selling price on Amazon
        sales_rank: Current sales rank
        estimated_monthly_sales: ML-estimated units/month
        profit_potential: Estimated profit per unit
        num_sellers: Number of active sellers
        num_fba_sellers: Number of FBA sellers
        buy_box_owner: Current Buy Box owner (seller name)
        price_history_avg: Average price over last 90 days
        price_stability: Standard deviation of price
        is_underserved: ML classification (True/False)
        opportunity_score: 0-100 ranking for opportunity quality
        status: active, archived, rejected
        notes: Manual notes and observations
        created_at: When product was added to system
        last_updated: When product metrics were last updated
    """
    __tablename__ = "products"
    
    asin = Column(String(10), primary_key=True, index=True)
    upc = Column(String(14), nullable=True, index=True)
    title = Column(String(500))
    category = Column(String(200))
    
    # Current Metrics
    current_price = Column(Numeric(10, 2))
    sales_rank = Column(Integer, nullable=True)
    estimated_monthly_sales = Column(Integer, default=0)
    profit_potential = Column(Numeric(10, 2), default=0)
    
    # Competition Metrics
    num_sellers = Column(Integer, default=0)
    num_fba_sellers = Column(Integer, default=0)
    buy_box_owner = Column(String(200), nullable=True)
    
    # Price History
    price_history_avg = Column(Numeric(10, 2), nullable=True)
    price_stability = Column(Numeric(10, 2), nullable=True)
    
    # Classification
    is_underserved = Column(Boolean, default=False, index=True)
    opportunity_score = Column(Float, default=0.0)  # 0-100
    
    # Status
    status = Column(String(20), default="active", index=True)  # active, archived, rejected
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    suppliers = relationship("ProductSupplier", back_populates="product", cascade="all, delete-orphan")
    inventory = relationship("Inventory", back_populates="product", uselist=False, cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="product", cascade="all, delete-orphan")
    performance = relationship("Performance", back_populates="product", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_status_score', 'status', 'opportunity_score'),
        Index('idx_underserved', 'is_underserved'),
    )


# ============================================================================
# SUPPLIER MODEL
# ============================================================================
class Supplier(Base):
    """
    Represents a supplier/vendor for sourcing products.
    
    Attributes:
        supplier_id: Unique identifier
        name: Supplier name
        website: Supplier website URL
        contact_email: Contact email
        min_order_qty: Minimum order quantity
        lead_time_days: Days to deliver
        reliability_score: 0-100 based on historical performance
        last_order_date: When we last ordered from them
        total_orders: Lifetime number of orders
        status: active, inactive, blacklisted
    """
    __tablename__ = "suppliers"
    
    supplier_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), unique=True, index=True)
    website = Column(String(500), nullable=True)
    contact_email = Column(String(200), nullable=True)
    
    # Order Terms
    min_order_qty = Column(Integer, default=1)
    lead_time_days = Column(Integer, default=7)
    
    # Performance
    reliability_score = Column(Float, default=0.0)  # 0-100
    last_order_date = Column(DateTime, nullable=True)
    total_orders = Column(Integer, default=0)
    on_time_delivery_rate = Column(Float, default=1.0)  # 0-1
    
    # Status
    status = Column(String(20), default="active", index=True)  # active, inactive, blacklisted
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    product_suppliers = relationship("ProductSupplier", back_populates="supplier", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="supplier")


# ============================================================================
# PRODUCT-SUPPLIER JUNCTION TABLE
# ============================================================================
class ProductSupplier(Base):
    """
    Junction table linking products to suppliers with pricing information.
    """
    __tablename__ = "product_suppliers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    asin = Column(String(10), ForeignKey("products.asin"), index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.supplier_id"), index=True)
    
    # Pricing
    supplier_cost = Column(Numeric(10, 2))  # Cost per unit from supplier
    shipping_cost = Column(Numeric(10, 2), default=0)  # Shipping per unit
    total_cost = Column(Numeric(10, 2))  # Total landed cost
    
    # Profitability
    estimated_profit = Column(Numeric(10, 2))
    profit_margin = Column(Float)  # 0-1 (e.g., 0.25 = 25%)
    roi = Column(Float)  # Return on investment
    
    # Status
    is_preferred = Column(Boolean, default=False)
    status = Column(String(20), default="active")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    product = relationship("Product", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="product_suppliers")


# ============================================================================
# INVENTORY MODEL
# ============================================================================
class Inventory(Base):
    """
    Tracks current and forecasted inventory levels.
    
    Attributes:
        asin: Product ASIN (foreign key)
        current_stock: Units currently in Amazon FBA
        reserved: Units reserved for pending orders
        available: Units available for sale (current_stock - reserved)
        reorder_point: Trigger level for reordering
        safety_stock: Minimum buffer stock
        forecasted_stock_30d: Predicted stock in 30 days
        last_restock_date: When we last sent inventory to Amazon
        days_of_supply: Estimated days until stockout at current velocity
    """
    __tablename__ = "inventory"
    
    asin = Column(String(10), ForeignKey("products.asin"), primary_key=True)
    
    # Current Levels
    current_stock = Column(Integer, default=0)
    reserved = Column(Integer, default=0)
    available = Column(Integer, default=0)
    
    # Reorder Parameters
    reorder_point = Column(Integer, default=0)
    safety_stock = Column(Integer, default=0)
    
    # Forecasts
    forecasted_stock_30d = Column(Integer, nullable=True)
    forecasted_stock_60d = Column(Integer, nullable=True)
    
    # Timing
    last_restock_date = Column(DateTime, nullable=True)
    days_of_supply = Column(Float, default=0)  # Days until stockout
    
    # Status
    needs_reorder = Column(Boolean, default=False, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    product = relationship("Product", back_populates="inventory")


# ============================================================================
# PURCHASE ORDER MODEL
# ============================================================================
class PurchaseOrder(Base):
    """
    Tracks purchase orders for inventory replenishment.
    
    Attributes:
        po_id: Unique PO identifier
        asin: Product ASIN
        supplier_id: Supplier ID
        quantity: Units ordered
        unit_cost: Cost per unit
        total_cost: Total PO cost
        status: pending, confirmed, shipped, received, cancelled
        order_date: When PO was created
        expected_delivery: Expected arrival date
        actual_delivery: Actual arrival date
        notes: Any special notes or issues
    """
    __tablename__ = "purchase_orders"
    
    po_id = Column(String(50), primary_key=True, index=True)
    asin = Column(String(10), ForeignKey("products.asin"), index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.supplier_id"), index=True)
    
    # Order Details
    quantity = Column(Integer)
    unit_cost = Column(Numeric(10, 2))
    total_cost = Column(Numeric(10, 2))
    
    # Status & Tracking
    status = Column(String(20), default="pending", index=True)  # pending, confirmed, shipped, received, cancelled
    order_date = Column(DateTime, default=datetime.utcnow)
    expected_delivery = Column(DateTime, nullable=True)
    actual_delivery = Column(DateTime, nullable=True)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    product = relationship("Product", back_populates="purchase_orders")
    supplier = relationship("Supplier", back_populates="purchase_orders")


# ============================================================================
# PERFORMANCE METRICS MODEL
# ============================================================================
class Performance(Base):
    """
    Daily performance metrics for each product.
    
    Attributes:
        asin: Product ASIN
        date: Date of metrics
        units_sold: Units sold that day
        revenue: Total revenue that day
        cost_of_goods: Total COGS for units sold
        amazon_fees: Total Amazon fees
        net_profit: Net profit for the day
        buy_box_owned: True if we owned Buy Box that day
        buy_box_percentage: % of day we owned Buy Box
        price: Price at end of day
        competitor_price: Lowest competitor price
        sales_rank: Sales rank at end of day
    """
    __tablename__ = "performance"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    asin = Column(String(10), ForeignKey("products.asin"), index=True)
    date = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Sales Metrics
    units_sold = Column(Integer, default=0)
    revenue = Column(Numeric(10, 2), default=0)
    cost_of_goods = Column(Numeric(10, 2), default=0)
    amazon_fees = Column(Numeric(10, 2), default=0)
    net_profit = Column(Numeric(10, 2), default=0)
    
    # Buy Box Metrics
    buy_box_owned = Column(Boolean, default=False)
    buy_box_percentage = Column(Float, default=0.0)  # 0-1
    
    # Pricing & Competition
    price = Column(Numeric(10, 2), nullable=True)
    competitor_price = Column(Numeric(10, 2), nullable=True)
    sales_rank = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    product = relationship("Product", back_populates="performance")
    
    # Indexes
    __table_args__ = (
        Index('idx_asin_date', 'asin', 'date'),
    )


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================
def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)
    print("✓ Database initialized successfully")


def get_db() -> Session:
    """Get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# DATABASE OPERATIONS
# ============================================================================
class DatabaseOperations:
    """High-level database operations for the Replens system."""
    
    @staticmethod
    def get_session() -> Session:
        """Get a new database session."""
        return SessionLocal()
    
    @staticmethod
    def add_product(session: Session, asin: str, title: str, category: str, **kwargs) -> Product:
        """Add a new product to the database."""
        product = Product(asin=asin, title=title, category=category, **kwargs)
        session.add(product)
        session.commit()
        return product
    
    @staticmethod
    def get_product(session: Session, asin: str) -> Optional[Product]:
        """Get a product by ASIN."""
        return session.query(Product).filter(Product.asin == asin).first()
    
    @staticmethod
    def get_underserved_products(session: Session, limit: int = 50) -> List[Product]:
        """Get top underserved products by opportunity score."""
        return session.query(Product)\
            .filter(Product.is_underserved == True, Product.status == "active")\
            .order_by(Product.opportunity_score.desc())\
            .limit(limit)\
            .all()
    
    @staticmethod
    def get_low_stock_products(session: Session) -> List[Product]:
        """Get products that need reordering."""
        return session.query(Product)\
            .join(Inventory)\
            .filter(Inventory.needs_reorder == True)\
            .all()
    
    @staticmethod
    def add_supplier(session: Session, name: str, **kwargs) -> Supplier:
        """Add a new supplier to the database."""
        supplier = Supplier(name=name, **kwargs)
        session.add(supplier)
        session.commit()
        return supplier
    
    @staticmethod
    def get_supplier(session: Session, supplier_id: int) -> Optional[Supplier]:
        """Get a supplier by ID."""
        return session.query(Supplier).filter(Supplier.supplier_id == supplier_id).first()
    
    @staticmethod
    def get_product_suppliers(session: Session, asin: str) -> List[ProductSupplier]:
        """Get all suppliers for a product, sorted by profitability."""
        return session.query(ProductSupplier)\
            .filter(ProductSupplier.asin == asin)\
            .order_by(ProductSupplier.profit_margin.desc())\
            .all()
    
    @staticmethod
    def create_purchase_order(session: Session, po_id: str, asin: str, supplier_id: int, 
                             quantity: int, unit_cost: Decimal) -> PurchaseOrder:
        """Create a new purchase order."""
        po = PurchaseOrder(
            po_id=po_id,
            asin=asin,
            supplier_id=supplier_id,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=Decimal(quantity) * unit_cost
        )
        session.add(po)
        session.commit()
        return po
    
    @staticmethod
    def record_performance(session: Session, asin: str, units_sold: int, revenue: Decimal,
                          cost_of_goods: Decimal, amazon_fees: Decimal, buy_box_owned: bool = False) -> Performance:
        """Record daily performance metrics."""
        net_profit = revenue - cost_of_goods - amazon_fees
        perf = Performance(
            asin=asin,
            units_sold=units_sold,
            revenue=revenue,
            cost_of_goods=cost_of_goods,
            amazon_fees=amazon_fees,
            net_profit=net_profit,
            buy_box_owned=buy_box_owned
        )
        session.add(perf)
        session.commit()
        return perf


if __name__ == "__main__":
    init_db()
