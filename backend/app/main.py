import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import admin, auth, catalogue, inventory, orders, organizations, search
from app.core.config import settings
from app.core.database import engine
from app.core.errors import AppError, register_error_handlers

logging.basicConfig(level=logging.INFO)

API_DESCRIPTION = """
ApexRx connects patients with pharmacies that report a medicine as available,
and pharmacies with suppliers that stock it.

* **Patients** search without an account (`/search`).
* **Pharmacies and suppliers** register an organization, upload verification
  documents, add staff, record stock and prices, and exchange purchase orders.
* **ApexRx admins** verify organizations and maintain the shared catalogue.

Authenticate with `POST /auth/login` and send `Authorization: Bearer <token>`.
"""

app = FastAPI(
    title="ApexRx API",
    description=API_DESCRIPTION,
    version="0.2.0",
    openapi_tags=[
        {"name": "Health"},
        {"name": "Authentication", "description": "Accounts and sessions"},
        {"name": "Search", "description": "Public patient search (no account)"},
        {"name": "Catalogue", "description": "Shared medicine catalogue"},
        {"name": "Organizations", "description": "Registration, members, locations, documents"},
        {"name": "Inventory", "description": "Stock and offers per location"},
        {"name": "Supplier discovery", "description": "Pharmacies search supplier stock"},
        {"name": "Purchase orders", "description": "Pharmacy to supplier ordering"},
        {"name": "Admin", "description": "Platform administration"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

register_error_handlers(app)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(search.router, prefix="/search", tags=["Search"])
app.include_router(catalogue.router, prefix="/catalogue", tags=["Catalogue"])
app.include_router(organizations.router, prefix="/organizations", tags=["Organizations"])
app.include_router(inventory.router, prefix="/organizations", tags=["Inventory"])
app.include_router(search.supplier_router, prefix="/supplier-offers", tags=["Supplier discovery"])
app.include_router(orders.router, prefix="/purchase-orders", tags=["Purchase orders"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(search.legacy_router, tags=["Search"])


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise AppError("Database unavailable.", status_code=503) from None
    return {"status": "healthy", "database": "connected"}
