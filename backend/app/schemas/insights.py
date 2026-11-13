from decimal import Decimal

from pydantic import BaseModel


class StockHealth(BaseModel):
    """Stock rows by level: out (0 or less), low (at or under the low-stock
    threshold) and in stock. Rows without an offer use the default threshold (5)."""

    in_stock: int
    low_stock: int
    out_of_stock: int
    total: int


class TopProduct(BaseModel):
    product_id: int
    product_name: str
    drug_name: str
    strength: str | None
    pack_size: str | None
    quantity: int


class DashboardInsights(BaseModel):
    """Management view of an organization (owners and managers only)."""

    organization_id: int
    location_id: int | None
    stock_health: StockHealth
    order_pipeline: dict[str, int]
    open_order_value: Decimal
    currency: str
    top_requested: list[TopProduct]
