
from datetime import date

from fastapi import FastAPI, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import SessionLocal, engine
from app.models import Batch, Drug, Location, Product, Stock
from app.api.auth import router as auth_router

app = FastAPI(
    title="ApexRx API",
    description="Backend API for medicine availability and pharmacy inventory.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5501",
        "http://localhost:5501",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"],
)


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": "unavailable",
            },
        )


@app.get("/medicines/availability", tags=["Medicines"])
def get_medicine_availability():
    statement = (
        select(
            Drug.name.label("drug_name"),
            Product.product_name,
            Product.brand,
            Product.strength,
            Product.dosage_form,
            Location.name.label("pharmacy_name"),
            Location.city,
            Stock.quantity,
            Stock.availability,
            Batch.batch_number,
            Batch.expiry_date,
        )
        .select_from(Stock)
        .join(Location, Stock.location_id == Location.location_id)
        .join(Batch, Stock.batch_id == Batch.batch_id)
        .join(Product, Batch.product_id == Product.product_id)
        .join(Drug, Product.drug_id == Drug.drug_id)
        .where(
            Stock.quantity > 0,
            Batch.expiry_date >= date.today(),
        )
        .order_by(Drug.name, Location.name)
    )

    try:
        with SessionLocal() as db:
            results = db.execute(statement).mappings().all()
            return [dict(row) for row in results]

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve medicine availability.",
        )