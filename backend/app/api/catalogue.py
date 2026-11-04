"""Shared medicine catalogue. Anyone can browse it; only platform admins edit it."""

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, DbSession, Pagination
from app.core.errors import AppError, Conflict, NotFound
from app.models import Drug, Product
from app.schemas.catalogue import (
    DrugCreate,
    DrugResponse,
    DrugUpdate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from app.schemas.common import Page

router = APIRouter()


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(value: str) -> str:
    return f"%{escape_like(value.strip())}%"


def product_response(product: Product) -> ProductResponse:
    return ProductResponse(
        product_id=product.product_id,
        drug_id=product.drug_id,
        drug_name=product.drug.name,
        product_name=product.product_name,
        brand=product.brand,
        strength=product.strength,
        dosage_form=product.dosage_form,
        pack_size=product.pack_size,
        barcode=product.barcode,
        manufacturer=product.manufacturer,
        is_active=product.is_active,
        created_at=product.created_at,
    )


def get_active_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None or not product.is_active:
        raise NotFound(f"Product {product_id} not found in the catalogue.")
    return product


def _drug_name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Drug.drug_id).where(func.lower(func.btrim(Drug.name)) == name.strip().lower())
    if exclude_id is not None:
        stmt = stmt.where(Drug.drug_id != exclude_id)
    return db.scalar(stmt) is not None


def _product_conflict(db: Session, product: Product) -> str | None:
    """Mirror uq_product_identity / uq_product_barcode with a friendly message."""
    norm = lambda col: func.lower(func.btrim(func.coalesce(col, "")))  # noqa: E731
    val = lambda v: (v or "").strip().lower()  # noqa: E731
    identity = select(Product.product_id).where(
        Product.drug_id == product.drug_id,
        norm(Product.brand) == val(product.brand),
        norm(Product.strength) == val(product.strength),
        norm(Product.dosage_form) == val(product.dosage_form),
        norm(Product.pack_size) == val(product.pack_size),
        norm(Product.manufacturer) == val(product.manufacturer),
    )
    if product.product_id is not None:
        identity = identity.where(Product.product_id != product.product_id)
    existing = db.scalar(identity)
    if existing:
        return f"An identical catalogue product already exists (product_id {existing})."
    if product.barcode:
        barcode = select(Product.product_id).where(
            func.lower(func.btrim(Product.barcode)) == product.barcode.strip().lower()
        )
        if product.product_id is not None:
            barcode = barcode.where(Product.product_id != product.product_id)
        existing = db.scalar(barcode)
        if existing:
            return f"Barcode is already used by product_id {existing}."
    return None


# Drugs ------------------------------------------------------------------------
@router.get("/drugs", response_model=Page[DrugResponse])
def list_drugs(
    db: DbSession,
    page: Pagination,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    limit, offset = page
    stmt = select(Drug)
    if q and q.strip():
        stmt = stmt.where(or_(Drug.name.ilike(contains(q)), Drug.therapeutic_class.ilike(contains(q))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Drug.name).limit(limit).offset(offset)).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/drugs/{drug_id}", response_model=DrugResponse)
def get_drug(drug_id: int, db: DbSession):
    drug = db.get(Drug, drug_id)
    if drug is None:
        raise NotFound("Drug not found.")
    return drug


@router.post("/drugs", response_model=DrugResponse, status_code=status.HTTP_201_CREATED)
def create_drug(payload: DrugCreate, _: AdminUser, db: DbSession):
    if _drug_name_taken(db, payload.name):
        raise Conflict("A drug with this name already exists.")
    drug = Drug(**payload.model_dump())
    db.add(drug)
    db.commit()
    return drug


@router.patch("/drugs/{drug_id}", response_model=DrugResponse)
def update_drug(drug_id: int, payload: DrugUpdate, _: AdminUser, db: DbSession):
    drug = db.get(Drug, drug_id)
    if drug is None:
        raise NotFound("Drug not found.")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        if data["name"] is None:
            raise AppError("name cannot be null.")
        if _drug_name_taken(db, data["name"], exclude_id=drug_id):
            raise Conflict("A drug with this name already exists.")
    for field, value in data.items():
        setattr(drug, field, value)
    db.commit()
    return drug


# Products ---------------------------------------------------------------------
@router.get("/products", response_model=Page[ProductResponse])
def list_products(
    db: DbSession,
    page: Pagination,
    q: Annotated[
        str | None, Query(max_length=100, description="Matches product, brand, drug name or barcode")
    ] = None,
    drug_id: int | None = None,
    include_inactive: bool = False,
):
    limit, offset = page
    stmt = select(Product).join(Drug, Drug.drug_id == Product.drug_id)
    if not include_inactive:
        stmt = stmt.where(Product.is_active.is_(True))
    if drug_id is not None:
        stmt = stmt.where(Product.drug_id == drug_id)
    if q and q.strip():
        pattern = contains(q)
        stmt = stmt.where(
            or_(
                Product.product_name.ilike(pattern),
                Product.brand.ilike(pattern),
                Drug.name.ilike(pattern),
                Product.barcode == q.strip(),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    products = db.scalars(
        stmt.order_by(Drug.name, Product.product_name, Product.product_id).limit(limit).offset(offset)
    ).all()
    return Page(items=[product_response(p) for p in products], total=total, limit=limit, offset=offset)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: int, db: DbSession):
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("Product not found.")
    return product_response(product)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, _: AdminUser, db: DbSession):
    if db.get(Drug, payload.drug_id) is None:
        raise NotFound("Drug not found.")
    product = Product(**payload.model_dump())
    if conflict := _product_conflict(db, product):
        raise Conflict(conflict)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product_response(product)


@router.patch("/products/{product_id}", response_model=ProductResponse)
def update_product(product_id: int, payload: ProductUpdate, _: AdminUser, db: DbSession):
    """Edit a catalogue product. Set ``is_active: false`` to retire it; retired
    products disappear from patient and supplier search."""
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("Product not found.")
    data = payload.model_dump(exclude_unset=True)
    for required in ("drug_id", "product_name", "is_active"):
        if required in data and data[required] is None:
            raise AppError(f"{required} cannot be null.")
    if "drug_id" in data and db.get(Drug, data["drug_id"]) is None:
        raise NotFound("Drug not found.")
    with db.no_autoflush:
        for field, value in data.items():
            setattr(product, field, value)
        if conflict := _product_conflict(db, product):
            db.rollback()
            raise Conflict(conflict)
    db.commit()
    db.refresh(product)
    return product_response(product)
