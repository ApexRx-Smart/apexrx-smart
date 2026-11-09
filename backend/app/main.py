import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import admin, auth, catalogue, dev, email_verification, inventory, orders, organizations, search
from app.core import schema
from app.core.config import settings
from app.core.database import engine
from app.core.errors import AppError, register_error_handlers
from app.services.email import email_configuration_problem

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

_log = logging.getLogger("apexrx")

# Development behaviour (mock email, /dev endpoints) must never run on the hosted
# service: refuse to start rather than expose test verification links.
if os.environ.get("RENDER") and not settings.is_production:
    raise RuntimeError(
        f"APP_ENV={settings.app_env!r} on Render. The hosted service must run with APP_ENV=production."
    )

# Code that expects a newer schema than the database has breaks sign-in and
# every user query; say so loudly at startup (the service keeps running so
# public search stays up, and /health reports 503 until it is fixed).
try:
    with engine.connect() as _connection:
        _schema_problem = schema.schema_problem(_connection)
    if _schema_problem:
        _log.critical(_schema_problem)
except SQLAlchemyError as _exc:
    _log.error("Could not check the database schema version at startup: %s", type(_exc).__name__)

_email_problem = email_configuration_problem()
if _email_problem:
    _log.warning(
        "Email verification is unavailable (%s). Sending verification emails returns 503%s.",
        _email_problem,
        "; new pharmacies and suppliers cannot register until it is configured"
        if settings.email_verification_required
        else "",
    )

if os.environ.get("RENDER") and not settings.trusted_client_ip_header:
    logging.getLogger("apexrx").warning(
        "TRUSTED_CLIENT_IP_HEADER is not set: on Render every request comes from a private proxy address, "
        "so per-IP login limiting is inactive (per-account and per-device limits still apply). Only set it "
        "after verifying that the proxy overwrites the header (see tools/render-ip-check)."
    )

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(email_verification.router, prefix="/auth/email", tags=["Email verification"])
app.include_router(search.router, prefix="/search", tags=["Search"])
app.include_router(catalogue.router, prefix="/catalogue", tags=["Catalogue"])
app.include_router(organizations.router, prefix="/organizations", tags=["Organizations"])
app.include_router(inventory.router, prefix="/organizations", tags=["Inventory"])
app.include_router(search.supplier_router, prefix="/supplier-offers", tags=["Supplier discovery"])
app.include_router(orders.router, prefix="/purchase-orders", tags=["Purchase orders"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(search.legacy_router, tags=["Search"])
if not settings.is_production:
    # Development/test only (the endpoint also refuses in production itself).
    app.include_router(dev.router, prefix="/dev", tags=["Development only"])


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            problem = schema.schema_problem(connection)
    except SQLAlchemyError:
        raise AppError("Database unavailable.", status_code=503) from None
    if problem:
        raise AppError(problem, status_code=503, extra={"database": "connected", "schema": "outdated"})
    return {"status": "healthy", "database": "connected", "schema": "up to date"}
