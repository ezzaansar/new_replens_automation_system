"""
Clear Products from Database

Removes all products so you can re-run discovery with corrected prices.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import SessionLocal, Product, ProductSupplier

print("="*80)
print("CLEAR PRODUCTS DATABASE")
print("="*80)

session = SessionLocal()

# Count current records
product_count = session.query(Product).count()
match_count = session.query(ProductSupplier).count()

print(f"\nCurrent database:")
print(f"  Products: {product_count}")
print(f"  Product-Supplier matches: {match_count}")

if product_count == 0:
    print("\n✓ Database already empty")
    session.close()
    exit(0)

print(f"\n⚠️  This will DELETE all {product_count} products and {match_count} matches")
response = input("\nProceed? (yes/no): ").lower()

if response == 'yes':
    # Delete product-supplier matches first (foreign key constraint)
    deleted_matches = session.query(ProductSupplier).delete()

    # Delete products
    deleted_products = session.query(Product).delete()

    session.commit()

    print(f"\n✓ Deleted {deleted_products} products")
    print(f"✓ Deleted {deleted_matches} product-supplier matches")
    print("\nDatabase cleared! Ready for fresh discovery.")
    print("\nNext step:")
    print("  uv run python -m src.phases.phase_2_auto_discovery --keywords 'your keywords'")
else:
    print("\nCancelled. No changes made.")

session.close()
