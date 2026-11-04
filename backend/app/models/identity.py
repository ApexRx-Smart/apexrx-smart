"""Users, organizations, memberships, locations and verification documents."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    created_at_column,
    identity_pk,
    server_timestamp_column,
)


class User(Base):
    __tablename__ = "app_user"

    user_id: Mapped[int] = identity_pk()
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Platform-level administrator (ApexRx staff). Separate from membership roles.
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = server_timestamp_column()

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", passive_deletes=True
    )

    __table_args__ = (
        Index("uq_app_user_email", func.lower(func.btrim(email)), unique=True),
    )


class Organization(Base):
    __tablename__ = "organization"

    organization_id: Mapped[int] = identity_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'"), default="pending"
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = server_timestamp_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    review_notes: Mapped[str | None] = mapped_column(Text)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", passive_deletes=True
    )
    locations: Mapped[list["Location"]] = relationship(
        back_populates="organization", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("type IN ('pharmacy', 'supplier')", name="organization_type_check"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'suspended')",
            name="organization_status_check",
        ),
        CheckConstraint("status = 'pending' OR reviewed_at IS NOT NULL", name="organization_check"),
        UniqueConstraint("organization_id", "type", name="organization_organization_id_type_key"),
        Index("idx_organization_status", "type", "status"),
    )


class Membership(Base):
    __tablename__ = "membership"

    membership_id: Mapped[int] = identity_pk()
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    created_at: Mapped[datetime] = created_at_column()

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")

    __table_args__ = (
        CheckConstraint("role IN ('owner', 'manager', 'staff')", name="membership_role_check"),
        UniqueConstraint("user_id", "organization_id", name="membership_user_id_organization_id_key"),
        Index("idx_membership_user", "user_id"),
        Index("idx_membership_organization", "organization_id"),
    )


class Location(Base):
    """A pharmacy branch or a supplier warehouse (the org's type says which)."""

    __tablename__ = "location"

    location_id: Mapped[int] = identity_pk()
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    phone: Mapped[str | None] = mapped_column(String(30))
    whatsapp_phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = server_timestamp_column()

    organization: Mapped[Organization] = relationship(back_populates="locations")

    __table_args__ = (
        UniqueConstraint("location_id", "organization_id", name="location_location_id_organization_id_key"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="location_latitude_check"),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180", name="location_longitude_check"
        ),
        Index("idx_location_organization", "organization_id"),
        Index(
            "idx_location_coords",
            "latitude",
            "longitude",
            postgresql_where=text("latitude IS NOT NULL AND longitude IS NOT NULL"),
        ),
    )


class OrganizationDocument(Base):
    __tablename__ = "organization_document"

    document_id: Mapped[int] = identity_pk()
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'"), default="pending"
    )
    uploaded_at: Mapped[datetime] = created_at_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="organization_document_file_size_bytes_check"),
        CheckConstraint(
            "verification_status IN ('pending', 'approved', 'rejected')",
            name="organization_document_verification_status_check",
        ),
        CheckConstraint(
            "(verification_status = 'pending' AND reviewed_at IS NULL) "
            "OR (verification_status <> 'pending' AND reviewed_at IS NOT NULL)",
            name="organization_document_check",
        ),
        Index("idx_org_document_org", "organization_id", "verification_status"),
    )
