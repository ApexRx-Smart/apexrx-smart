"""Load demonstration data for local development.

    python -m app.scripts.seed_demo

Creates (if missing) an admin, an approved pharmacy with two Kigali branches,
an approved supplier with a warehouse, a small catalogue, stock and offers.
All demo accounts use the password ``demo-password``. Never run in production.
"""

import sys
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal, set_session_actor
from app.core.security import hash_password
from app.models import (
    Drug,
    Location,
    Membership,
    Organization,
    Product,
    ProductOffer,
    Stock,
    User,
)

PASSWORD = "demo-password"

CATALOGUE = [
    # drug, therapeutic class, product, brand, strength, form, pack
    ("Paracetamol", "Analgesic", "Panadol 500mg", "Panadol", "500mg", "tablet", "100 tablets"),
    ("Amoxicillin", "Antibiotic", "Amoxil 250mg", "Amoxil", "250mg", "capsule", "21 capsules"),
    ("Ibuprofen", "NSAID", "Brufen 400mg", "Brufen", "400mg", "tablet", "30 tablets"),
    ("Metformin", "Antidiabetic", "Glucophage 500mg", "Glucophage", "500mg", "tablet", "60 tablets"),
    ("Artemether/Lumefantrine", "Antimalarial", "Coartem 20/120", "Coartem", "20mg/120mg", "tablet", "24 tablets"),
]

# product index -> (quantity, price) per location
PHARMACY_STOCK = {
    "Kigali Central Pharmacy - Downtown": {0: (120, "1500"), 1: (3, "2500"), 2: (40, "1200"), 4: (0, "4000")},
    "Kigali Central Pharmacy - Kimironko": {0: (60, "1400"), 3: (25, "3000"), 4: (15, "3800")},
}
SUPPLIER_STOCK = {0: (5000, "900"), 1: (800, "1600"), 2: (1200, "700"), 3: (600, "2100"), 4: (300, "2900")}


def _user(db, email: str, name: str, admin: bool = False) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(name=name, email=email, password_hash=hash_password(PASSWORD), is_platform_admin=admin)
        db.add(user)
        db.flush()
    return user


def _org(db, name: str, type_: str, owner: User, admin: User) -> Organization:
    org = db.scalar(select(Organization).where(Organization.name == name))
    if org is None:
        org = Organization(
            name=name,
            type=type_,
            status="approved",
            reviewed_at=datetime.now(timezone.utc),
            reviewed_by=admin.user_id,
            review_notes="Demo data",
            phone="+250788000000",
        )
        db.add(org)
        db.flush()
        db.add(Membership(user_id=owner.user_id, organization_id=org.organization_id, role="owner"))
    return org


def _location(db, org: Organization, name: str, **fields) -> Location:
    loc = db.scalar(select(Location).where(Location.organization_id == org.organization_id, Location.name == name))
    if loc is None:
        loc = Location(organization_id=org.organization_id, name=name, **fields)
        db.add(loc)
        db.flush()
    return loc


def _stock(db, loc: Location, product: Product, quantity: int, price: str) -> None:
    if db.scalar(select(Stock).where(Stock.location_id == loc.location_id, Stock.product_id == product.product_id)):
        return
    db.add(Stock(location_id=loc.location_id, product_id=product.product_id, quantity=quantity))
    db.flush()
    db.add(ProductOffer(location_id=loc.location_id, product_id=product.product_id, unit_price=Decimal(price), currency="RWF"))


def main() -> int:
    with SessionLocal() as db:
        admin = _user(db, "admin@apexrx.example.com", "ApexRx Admin", admin=True)
        pharmacist = _user(db, "pharmacist@apexrx.example.com", "Demo Pharmacist")
        supplier_user = _user(db, "supplier@apexrx.example.com", "Demo Supplier")
        db.commit()

        products = []
        for drug_name, klass, product_name, brand, strength, form, pack in CATALOGUE:
            drug = db.scalar(select(Drug).where(func.lower(Drug.name) == drug_name.lower()))
            if drug is None:
                drug = Drug(name=drug_name, therapeutic_class=klass)
                db.add(drug)
                db.flush()
            product = db.scalar(select(Product).where(Product.product_name == product_name))
            if product is None:
                product = Product(
                    drug_id=drug.drug_id, product_name=product_name, brand=brand,
                    strength=strength, dosage_form=form, pack_size=pack,
                )
                db.add(product)
                db.flush()
            products.append(product)

        pharmacy = _org(db, "Kigali Central Pharmacy", "pharmacy", pharmacist, admin)
        supplier = _org(db, "Rwanda Medical Supplies", "supplier", supplier_user, admin)
        branches = {
            "Kigali Central Pharmacy - Downtown": _location(
                db, pharmacy, "Downtown", address="KN 4 Ave, Kigali", city="Kigali",
                latitude=Decimal("-1.944100"), longitude=Decimal("30.061900"), phone="+250788111111",
            ),
            "Kigali Central Pharmacy - Kimironko": _location(
                db, pharmacy, "Kimironko", address="KG 11 Ave, Kigali", city="Kigali",
                latitude=Decimal("-1.949500"), longitude=Decimal("30.126000"), phone="+250788222222",
            ),
        }
        warehouse = _location(
            db, supplier, "Main Warehouse", address="Kigali Special Economic Zone", city="Kigali",
            latitude=Decimal("-1.970600"), longitude=Decimal("30.104400"),
            phone="+250788333333", whatsapp_phone="+250788333333",
        )
        db.commit()

        # Stock writes need a transaction actor (the schema's audit triggers).
        set_session_actor(db, pharmacist.user_id)
        for key, entries in PHARMACY_STOCK.items():
            for index, (qty, price) in entries.items():
                _stock(db, branches[key], products[index], qty, price)
        db.commit()

        set_session_actor(db, supplier_user.user_id)
        for index, (qty, price) in SUPPLIER_STOCK.items():
            _stock(db, warehouse, products[index], qty, price)
        db.commit()

    print("Demo data ready. Accounts (password: demo-password):")
    print("  admin@apexrx.example.com       platform admin")
    print("  pharmacist@apexrx.example.com  owner of Kigali Central Pharmacy")
    print("  supplier@apexrx.example.com    owner of Rwanda Medical Supplies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
