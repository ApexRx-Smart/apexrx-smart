"""Discovery.

* Patients (no account) search pharmacies through the ``patient_availability``
  view: availability status and price only, never exact quantities.
* Pharmacy members search suppliers through the ``supplier_listing`` view,
  which includes exact quantities and contact details.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Query
from sqlalchemy import Float, and_, case, cast, func, null, or_, select
from sqlalchemy.orm import Session

from app.api.catalogue import contains
from app.api.deps import CurrentUser, DbSession, Pagination, get_org_access
from app.core.errors import AppError, NotFound
from app.models import (
    Drug,
    Location,
    Organization,
    Product,
    SearchEvent,
    patient_availability,
    supplier_listing,
)
from app.models.enums import AvailabilityStatus, OrganizationStatus, OrganizationType
from app.schemas.common import Page
from app.schemas.search import (
    LegacyAvailability,
    MedicineMatch,
    PharmacyAvailability,
    PharmacyLocationDetail,
    PharmacySort,
    SupplierOffer,
    SupplierSort,
)

router = APIRouter()
supplier_router = APIRouter()

EARTH_RADIUS_KM = 6371.0
SEARCH_TEXT = Annotated[str | None, Query(max_length=100, description="Medicine, brand or product name")]
LAT = Annotated[float | None, Query(ge=-90, le=90)]
LNG = Annotated[float | None, Query(ge=-180, le=180)]
RADIUS = Annotated[float | None, Query(gt=0, le=500, description="Requires lat/lng")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _distance_km(lat_col, lng_col, lat: float, lng: float):
    """Haversine distance in km as a SQL expression (NULL when no coordinates).

    The explicit CASE matters: PostgreSQL's LEAST() ignores NULLs, so without it
    a location with no coordinates came out as half the Earth away (~20,015 km)."""
    lat1, lng1 = func.radians(lat), func.radians(lng)
    lat2, lng2 = func.radians(cast(lat_col, Float)), func.radians(cast(lng_col, Float))
    a = func.power(func.sin((lat2 - lat1) / 2), 2) + func.cos(lat1) * func.cos(lat2) * func.power(
        func.sin((lng2 - lng1) / 2), 2
    )
    distance = 2 * EARTH_RADIUS_KM * func.asin(func.least(1.0, func.sqrt(a)))
    return case((or_(lat_col.is_(None), lng_col.is_(None)), null()), else_=distance)


def _validate_geo(lat, lng, radius_km) -> None:
    if (lat is None) != (lng is None):
        raise AppError("lat and lng must be provided together.")
    if radius_km is not None and lat is None:
        raise AppError("radius_km requires lat and lng.")


def _product_filter(q: str | None, product_id: int | None, drug_id: int | None, product_col, drug_col):
    conditions = []
    if product_id is not None:
        conditions.append(product_col == product_id)
    if drug_id is not None:
        conditions.append(drug_col == drug_id)
    if q and q.strip():
        pattern = contains(q)
        conditions.append(
            or_(Product.product_name.ilike(pattern), Product.brand.ilike(pattern), Drug.name.ilike(pattern))
        )
    return conditions


def directions_url(latitude, longitude, address: str | None) -> str | None:
    if latitude is not None and longitude is not None:
        destination = f"{latitude},{longitude}"
    elif address:
        destination = address
    else:
        return None
    return "https://www.google.com/maps/dir/?" + urlencode({"api": "1", "destination": destination})


def whatsapp_url(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return f"https://wa.me/{quote(digits)}" if len(digits) >= 8 else None


def _coarse(value: float | None) -> Decimal | None:
    # ~1 km precision: enough for demand mapping, not enough to locate a person.
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _log_search(db: Session, query_text: str, product_id, drug_id, lat, lng, results: int) -> None:
    try:
        db.add(
            SearchEvent(
                query_text=query_text[:255],
                product_id=product_id,
                drug_id=drug_id,
                approx_latitude=_coarse(lat),
                approx_longitude=_coarse(lng),
                results_count=results,
            )
        )
        db.commit()
    except Exception:  # analytics must never break search
        db.rollback()


# ---------------------------------------------------------------------------
# Patient-facing (public)
# ---------------------------------------------------------------------------
@router.get("/medicines", response_model=Page[MedicineMatch])
def search_medicines(
    db: DbSession,
    page: Pagination,
    q: Annotated[str, Query(min_length=2, max_length=100)],
):
    """Find catalogue medicines by name (autocomplete), with how many pharmacy
    locations currently report them available."""
    limit, offset = page
    available = (
        select(patient_availability.c.product_id, func.count().label("n"))
        .where(patient_availability.c.availability_status != AvailabilityStatus.UNAVAILABLE)
        .group_by(patient_availability.c.product_id)
        .subquery()
    )
    pattern = contains(q)
    stmt = (
        select(Product, Drug, func.coalesce(available.c.n, 0).label("available_count"))
        .join(Drug, Drug.drug_id == Product.drug_id)
        .outerjoin(available, available.c.product_id == Product.product_id)
        .where(
            Product.is_active.is_(True),
            or_(Product.product_name.ilike(pattern), Product.brand.ilike(pattern), Drug.name.ilike(pattern)),
        )
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(
        stmt.order_by(func.coalesce(available.c.n, 0).desc(), Drug.name, Product.product_name)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        MedicineMatch(
            product_id=p.product_id,
            product_name=p.product_name,
            drug_id=d.drug_id,
            drug_name=d.name,
            brand=p.brand,
            strength=p.strength,
            dosage_form=p.dosage_form,
            pack_size=p.pack_size,
            available_pharmacy_count=n,
        )
        for p, d, n in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


def _pharmacy_availability(row, distance) -> PharmacyAvailability:
    pa = row._mapping
    return PharmacyAvailability(
        offer_id=pa["offer_id"],
        product_id=pa["product_id"],
        product_name=pa["product_name"],
        drug_id=pa["drug_id"],
        drug_name=pa["drug_name"],
        strength=pa["strength"],
        dosage_form=pa["dosage_form"],
        pharmacy_organization_id=pa["pharmacy_organization_id"],
        pharmacy_name=pa["pharmacy_name"],
        location_id=pa["location_id"],
        location_name=pa["location_name"],
        address=pa["address"],
        latitude=pa["latitude"],
        longitude=pa["longitude"],
        phone=pa["phone"],
        unit_price=pa["unit_price"],
        currency=pa["currency"],
        availability_status=pa["availability_status"],
        last_updated=pa["last_updated"],
        distance_km=round(distance, 2) if distance is not None else None,
        directions_url=directions_url(pa["latitude"], pa["longitude"], pa["address"]),
    )


def _patient_query(lat, lng):
    pa = patient_availability.c
    distance = _distance_km(pa.latitude, pa.longitude, lat, lng) if lat is not None else None
    columns = [
        *patient_availability.c,
        Product.product_name,
        Product.strength,
        Product.dosage_form,
        Drug.name.label("drug_name"),
        (distance if distance is not None else cast(null(), Float)).label("distance_km"),
    ]
    stmt = (
        select(*columns)
        .select_from(patient_availability)
        .join(Product, Product.product_id == pa.product_id)
        .join(Drug, Drug.drug_id == pa.drug_id)
    )
    return stmt, distance


@router.get("/pharmacies", response_model=Page[PharmacyAvailability])
def search_pharmacies(
    db: DbSession,
    page: Pagination,
    q: SEARCH_TEXT = None,
    product_id: int | None = None,
    drug_id: int | None = None,
    lat: LAT = None,
    lng: LNG = None,
    radius_km: RADIUS = None,
    availability: Annotated[
        list[AvailabilityStatus] | None,
        Query(description="Defaults to in_stock and low_stock"),
    ] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: PharmacySort | None = None,
    record: Annotated[
        bool,
        Query(description="Count this request in search insights. The expanded results page sends "
                          "false when it only refines a search the patient already made."),
    ] = True,
):
    """Pharmacies reporting a medicine, with price, availability status,
    freshness and (when lat/lng are given) distance. Public: no account needed.

    Filters combine: text or ids, price range, radius. Branches without
    coordinates have no distance (never an estimate): a radius excludes them and
    the distance sort lists them last.

    Default sort: distance when lat/lng are given, otherwise price."""
    _validate_geo(lat, lng, radius_km)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise AppError("min_price cannot be greater than max_price.")
    conditions = _product_filter(q, product_id, drug_id, patient_availability.c.product_id, patient_availability.c.drug_id)
    if not conditions:
        raise AppError("Provide q, product_id or drug_id.")
    limit, offset = page
    pa = patient_availability.c
    statuses = availability or [AvailabilityStatus.IN_STOCK, AvailabilityStatus.LOW_STOCK]

    stmt, distance = _patient_query(lat, lng)
    stmt = stmt.where(*conditions, pa.availability_status.in_([s.value for s in statuses]))
    if min_price is not None:
        stmt = stmt.where(pa.unit_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(pa.unit_price <= max_price)
    if radius_km is not None:
        stmt = stmt.where(distance <= radius_km)

    sort = sort or (PharmacySort.DISTANCE if lat is not None else PharmacySort.PRICE)
    if sort == PharmacySort.DISTANCE and distance is None:
        raise AppError("Sorting by distance requires lat and lng.")
    order = {
        PharmacySort.DISTANCE: [distance.asc().nulls_last()] if distance is not None else [],
        PharmacySort.PRICE: [pa.unit_price.asc()],
        PharmacySort.PRICE_DESC: [pa.unit_price.desc()],
        PharmacySort.FRESHNESS: [pa.last_updated.desc()],
    }[sort]

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(*order, pa.offer_id).limit(limit).offset(offset)).all()
    items = [_pharmacy_availability(r, r._mapping["distance_km"]) for r in rows]

    if offset == 0 and record:
        _log_search(db, (q or "").strip() or f"product:{product_id or ''} drug:{drug_id or ''}",
                    product_id, drug_id, lat, lng, total)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/pharmacies/{location_id}", response_model=PharmacyLocationDetail)
def get_pharmacy_location(location_id: int, db: DbSession, lat: LAT = None, lng: LNG = None):
    """A pharmacy branch's public details, directions link and listed medicines."""
    _validate_geo(lat, lng, None)
    row = db.execute(
        select(Location, Organization)
        .join(Organization, Organization.organization_id == Location.organization_id)
        .where(
            Location.location_id == location_id,
            Location.is_active.is_(True),
            Organization.type == OrganizationType.PHARMACY,
            Organization.status == OrganizationStatus.APPROVED,
        )
    ).one_or_none()
    if row is None:
        raise NotFound("Pharmacy not found.")
    location, organization = row
    stmt, _ = _patient_query(lat, lng)
    medicines = db.execute(
        stmt.where(patient_availability.c.location_id == location_id).order_by(
            "drug_name", Product.product_name
        )
    ).all()
    return PharmacyLocationDetail(
        pharmacy_organization_id=organization.organization_id,
        pharmacy_name=organization.name,
        location_id=location.location_id,
        location_name=location.name,
        address=location.address,
        city=location.city,
        region=location.region,
        latitude=location.latitude,
        longitude=location.longitude,
        phone=location.phone,
        directions_url=directions_url(location.latitude, location.longitude, location.address),
        medicines=[_pharmacy_availability(r, r._mapping["distance_km"]) for r in medicines],
    )


# ---------------------------------------------------------------------------
# Pharmacy-facing supplier discovery
# ---------------------------------------------------------------------------
@supplier_router.get("", response_model=Page[SupplierOffer])
def search_supplier_offers(
    user: CurrentUser,
    db: DbSession,
    page: Pagination,
    pharmacy_organization_id: Annotated[int, Query(description="The pharmacy you are acting for")],
    q: SEARCH_TEXT = None,
    product_id: int | None = None,
    drug_id: int | None = None,
    supplier_organization_id: int | None = None,
    lat: LAT = None,
    lng: LNG = None,
    radius_km: RADIUS = None,
    min_quantity: Annotated[int | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    sort: SupplierSort = SupplierSort.PRICE,
):
    """Supplier offers with exact stock, price, location and contact links.
    Only members of an approved pharmacy can search suppliers."""
    get_org_access(
        db, user, pharmacy_organization_id, org_type=OrganizationType.PHARMACY, require_approved=True
    )
    _validate_geo(lat, lng, radius_km)
    sl = supplier_listing.c
    conditions = _product_filter(q, product_id, drug_id, sl.product_id, sl.drug_id)
    if supplier_organization_id is not None:
        conditions.append(sl.supplier_organization_id == supplier_organization_id)
    if not conditions:
        raise AppError("Provide q, product_id, drug_id or supplier_organization_id.")
    limit, offset = page

    distance = _distance_km(sl.latitude, sl.longitude, lat, lng) if lat is not None else None
    stmt = (
        select(
            *supplier_listing.c,
            Product.product_name,
            Product.strength,
            Product.dosage_form,
            Product.pack_size,
            Drug.name.label("drug_name"),
            (distance if distance is not None else cast(null(), Float)).label("distance_km"),
        )
        .select_from(supplier_listing)
        .join(Product, Product.product_id == sl.product_id)
        .join(Drug, Drug.drug_id == sl.drug_id)
        .where(and_(*conditions))
    )
    if min_quantity is not None:
        stmt = stmt.where(sl.quantity >= min_quantity)
    else:
        stmt = stmt.where(sl.quantity > 0)
    if max_price is not None:
        stmt = stmt.where(sl.unit_price <= max_price)
    if radius_km is not None:
        stmt = stmt.where(distance <= radius_km)

    if sort == SupplierSort.DISTANCE and distance is None:
        raise AppError("Sorting by distance requires lat and lng.")
    order = {
        SupplierSort.PRICE: [sl.unit_price.asc()],
        SupplierSort.DISTANCE: [distance.asc().nulls_last()] if distance is not None else [],
        SupplierSort.QUANTITY: [sl.quantity.desc()],
        SupplierSort.FRESHNESS: [sl.last_updated.desc()],
    }[sort]

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(*order, sl.offer_id).limit(limit).offset(offset)).all()
    items = []
    for r in rows:
        m = r._mapping
        items.append(
            SupplierOffer(
                offer_id=m["offer_id"],
                product_id=m["product_id"],
                product_name=m["product_name"],
                drug_id=m["drug_id"],
                drug_name=m["drug_name"],
                strength=m["strength"],
                dosage_form=m["dosage_form"],
                pack_size=m["pack_size"],
                supplier_organization_id=m["supplier_organization_id"],
                supplier_name=m["supplier_name"],
                supplier_location_id=m["supplier_location_id"],
                location_name=m["location_name"],
                city=m["city"],
                latitude=m["latitude"],
                longitude=m["longitude"],
                phone=m["phone"],
                whatsapp_phone=m["whatsapp_phone"],
                whatsapp_url=whatsapp_url(m["whatsapp_phone"]),
                unit_price=m["unit_price"],
                currency=m["currency"],
                quantity=m["quantity"],
                last_updated=m["last_updated"],
                distance_km=round(m["distance_km"], 2) if m["distance_km"] is not None else None,
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Compatibility endpoint for the current static frontend
# ---------------------------------------------------------------------------
legacy_router = APIRouter()

_LEGACY_STATUS = {
    AvailabilityStatus.IN_STOCK: "in_stock",
    AvailabilityStatus.LOW_STOCK: "low_stock",
    AvailabilityStatus.UNAVAILABLE: "out_of_stock",
}


@legacy_router.get("/medicines/availability", response_model=list[LegacyAvailability], deprecated=True)
def legacy_medicine_availability(db: DbSession):
    """Deprecated: kept so the existing homepage search keeps working until the
    frontend moves to ``GET /search/pharmacies``. Returns at most 500 listings,
    without exact quantities."""
    pa = patient_availability.c
    rows = db.execute(
        select(
            Drug.name.label("drug_name"),
            Product.product_name,
            Product.brand,
            Product.strength,
            Product.dosage_form,
            pa.pharmacy_name,
            Location.city,
            pa.availability_status,
            pa.unit_price,
            pa.currency,
            pa.last_updated,
        )
        .select_from(patient_availability)
        .join(Product, Product.product_id == pa.product_id)
        .join(Drug, Drug.drug_id == pa.drug_id)
        .join(Location, Location.location_id == pa.location_id)
        .order_by(Drug.name, pa.pharmacy_name)
        .limit(500)
    ).all()
    return [
        LegacyAvailability(
            **{k: v for k, v in r._mapping.items() if k != "availability_status"},
            availability=_LEGACY_STATUS[AvailabilityStatus(r.availability_status)],
        )
        for r in rows
    ]
