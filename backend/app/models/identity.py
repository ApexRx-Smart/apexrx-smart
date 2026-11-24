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
    Integer,
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
    # Set only by a successful email verification (an emailed link, see
    # app/services/email_verification.py). Required to register an organization.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set only by a successful SMS code check (app/services/otp.py): the number
    # that was verified and when. The phone counts as verified while
    # ``phone == verified_phone``.
    verified_phone: Mapped[str | None] = mapped_column(String(20))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # This account must verify its mobile number before using ApexRX (accounts
    # created while PHONE_VERIFICATION_REQUIRED is on, or that changed their
    # number since). False for every account that existed before.
    phone_verification_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # patient / pharmacy / supplier (app.models.enums.AccountType), set at
    # registration or by the invitation that created the account. Sign-in,
    # organization creation and invitations only accept the matching kind.
    account_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'patient'"), default="patient"
    )
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
        CheckConstraint("account_type IN ('patient', 'pharmacy', 'supplier')", name="app_user_account_type_check"),
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
    # When the application was submitted for review (every required document
    # uploaded); NULL while the registration is still in progress. See
    # app/services/applications.py.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    # Rwandan addresses: ``region`` holds the province, ``city`` the district,
    # then sector, cell and village; ``address`` is the street or landmark.
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(100))
    cell: Mapped[str | None] = mapped_column(String(100))
    village: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    phone: Mapped[str | None] = mapped_column(String(30))
    whatsapp_phone: Mapped[str | None] = mapped_column(String(30))
    # Pharmacy branches: quantity of each medicine kept back from patient
    # reservations (migration d4a7e2c9b1f8). Reservable = stock - held - this.
    reservation_min_stock: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
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
