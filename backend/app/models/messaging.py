"""Conversations between a pharmacy and a supplier, their messages, and
notifications. See migration b7c3e9d1f4a6 for the constraints and triggers."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_column, identity_pk


class Conversation(Base):
    __tablename__ = "conversation"

    conversation_id: Mapped[int] = identity_pk()
    pharmacy_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_organization_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pharmacy_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pharmacy'"), default="pharmacy"
    )
    supplier_org_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'supplier'"), default="supplier"
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    created_at: Mapped[datetime] = created_at_column()
    # Kept current by the message_guard trigger.
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "message"

    message_id: Mapped[int] = identity_pk()
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversation.conversation_id"), nullable=False
    )
    sender_organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id"), nullable=False
    )
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class ConversationRead(Base):
    __tablename__ = "conversation_read"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversation.conversation_id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.user_id"), primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = created_at_column()


class Notification(Base):
    __tablename__ = "notification"

    notification_id: Mapped[int] = identity_pk()
    # Exactly one recipient: an organization (every active member sees it) or,
    # for patient reservations, one user (notification_recipient_check).
    organization_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id")
    )
    recipient_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.user_id"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    from_organization_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("organization.organization_id")
    )
    conversation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("conversation.conversation_id")
    )
    procurement_request_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("procurement_request.procurement_request_id")
    )
    quotation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("quotation.quotation_id"))
    purchase_order_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("purchase_order.purchase_order_id")
    )
    reservation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("reservation.reservation_id"))
    created_at: Mapped[datetime] = created_at_column()


class NotificationRead(Base):
    __tablename__ = "notification_read"

    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.notification_id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.user_id"), primary_key=True)
    read_at: Mapped[datetime] = created_at_column()
