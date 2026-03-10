"""
Clear Suppliers from Database

Removes all suppliers and their product-supplier matches.
Useful when you want to re-run Phase 3 with updated filtering.
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import SessionLocal, Supplier, ProductSupplier

def clear_suppliers():
    """Clear all suppliers and product-supplier matches."""
    session = SessionLocal()

    try:
        # Count before deletion
        supplier_count = session.query(Supplier).count()
        match_count = session.query(ProductSupplier).count()

        print("="*80)
        print("CLEAR SUPPLIERS")
        print("="*80)
        print(f"\nCurrent database:")
        print(f"  Suppliers: {supplier_count}")
        print(f"  Product-Supplier matches: {match_count}")

        if supplier_count == 0 and match_count == 0:
            print("\n✓ Database already clean - no suppliers to delete")
            return

        # Confirm deletion
        print("\n⚠️  WARNING: This will delete ALL suppliers and matches!")
        print("   Products will NOT be deleted (they're safe)")
        print("\nType 'yes' to confirm deletion: ", end='')

        confirmation = input().strip().lower()

        if confirmation != 'yes':
            print("\n✗ Deletion cancelled")
            return

        print("\nDeleting...")

        # Delete product-supplier matches first (to be safe, though cascade should handle it)
        deleted_matches = session.query(ProductSupplier).delete()
        print(f"  ✓ Deleted {deleted_matches} product-supplier matches")

        # Delete suppliers (cascade will also delete matches)
        deleted_suppliers = session.query(Supplier).delete()
        print(f"  ✓ Deleted {deleted_suppliers} suppliers")

        # Commit changes
        session.commit()

        # Verify deletion
        remaining_suppliers = session.query(Supplier).count()
        remaining_matches = session.query(ProductSupplier).count()

        print("\n" + "="*80)
        print("DELETION COMPLETE")
        print("="*80)
        print(f"Suppliers removed: {supplier_count} → {remaining_suppliers}")
        print(f"Matches removed: {match_count} → {remaining_matches}")

        if remaining_suppliers == 0 and remaining_matches == 0:
            print("\n✓ Database successfully cleaned!")
            print("\nNext steps:")
            print("  1. Re-run Phase 3 with fixed filtering:")
            print("     uv run python -m src.phases.phase_3_sourcing_google")
            print("\n  2. Check dashboard for new supplier matches:")
            print("     uv run streamlit run src/dashboard/app.py")
        else:
            print(f"\n⚠️  Warning: {remaining_suppliers} suppliers and {remaining_matches} matches still remain")

    except Exception as e:
        session.rollback()
        print(f"\n✗ Error deleting suppliers: {e}")
        import traceback
        traceback.print_exc()

    finally:
        session.close()


def clear_suppliers_silent():
    """Clear suppliers without confirmation (for scripting)."""
    session = SessionLocal()

    try:
        supplier_count = session.query(Supplier).count()
        match_count = session.query(ProductSupplier).count()

        if supplier_count == 0 and match_count == 0:
            print("✓ No suppliers to delete")
            return

        # Delete without confirmation
        session.query(ProductSupplier).delete()
        session.query(Supplier).delete()
        session.commit()

        print(f"✓ Deleted {supplier_count} suppliers and {match_count} matches")

    except Exception as e:
        session.rollback()
        print(f"✗ Error: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Clear suppliers from database')
    parser.add_argument('--force', action='store_true', help='Delete without confirmation')
    args = parser.parse_args()

    if args.force:
        clear_suppliers_silent()
    else:
        clear_suppliers()
