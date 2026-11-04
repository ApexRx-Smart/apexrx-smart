"""Read-only mappings of the visibility views.

These live on a separate MetaData so Alembic autogenerate never tries to
create or drop them as tables. The views themselves are defined in the
migration / database/db_implementation_script.sql.
"""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
)

view_metadata = MetaData()

# Patient-facing: derived availability only, NEVER exact quantity.
patient_availability = Table(
    "patient_availability",
    view_metadata,
    Column("offer_id", BigInteger, primary_key=True),
    Column("product_id", BigInteger),
    Column("drug_id", BigInteger),
    Column("location_id", BigInteger),
    Column("pharmacy_organization_id", BigInteger),
    Column("pharmacy_name", String(255)),
    Column("location_name", String(255)),
    Column("address", Text),
    Column("latitude", Numeric(9, 6)),
    Column("longitude", Numeric(9, 6)),
    Column("phone", String(30)),
    Column("unit_price", Numeric(14, 2)),
    Column("currency", CHAR(3)),
    Column("availability_status", Text),
    Column("last_updated", DateTime(timezone=True)),
)

# Pharmacy-facing: supplier listings WITH exact quantities.
supplier_listing = Table(
    "supplier_listing",
    view_metadata,
    Column("offer_id", BigInteger, primary_key=True),
    Column("product_id", BigInteger),
    Column("drug_id", BigInteger),
    Column("supplier_location_id", BigInteger),
    Column("supplier_organization_id", BigInteger),
    Column("supplier_name", String(255)),
    Column("location_name", String(255)),
    Column("city", String(100)),
    Column("latitude", Numeric(9, 6)),
    Column("longitude", Numeric(9, 6)),
    Column("phone", String(30)),
    Column("whatsapp_phone", String(30)),
    Column("unit_price", Numeric(14, 2)),
    Column("currency", CHAR(3)),
    Column("quantity", Integer),
    Column("last_updated", DateTime(timezone=True)),
)
