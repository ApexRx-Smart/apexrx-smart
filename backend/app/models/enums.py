"""String enums matching the CHECK constraints in the v6 schema."""

from enum import StrEnum


class OrganizationType(StrEnum):
    PHARMACY = "pharmacy"
    SUPPLIER = "supplier"


class OrganizationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class MembershipRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    STAFF = "staff"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StockChangeType(StrEnum):
    INITIAL_STOCK = "initial_stock"
    QUANTITY_UPDATE = "quantity_update"
    STOCK_DELETED = "stock_deleted"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROCESSING = "processing"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class AvailabilityStatus(StrEnum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    UNAVAILABLE = "unavailable"
