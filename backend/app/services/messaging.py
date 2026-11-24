"""Conversations between a pharmacy and a supplier, and notifications.

A conversation belongs to the two organizations: every active member of
either one can read it and write in it. There is one conversation per
pharmacy and supplier pair; procurement requests and orders between the
two are shown alongside its messages.

Notifications are rows per organization (every active member sees them) or,
for patient reservations, per user; read state is kept per user.
"""

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.models import (
    ChatMessage,
    Conversation,
    ConversationRead,
    Membership,
    Notification,
    NotificationRead,
    Organization,
    User,
)
from app.models.enums import OrganizationStatus, OrganizationType


def member_org_ids(db: Session, user: User, org_ids: list[int]) -> list[int]:
    """Which of ``org_ids`` the user acts for: an active member, of an APPROVED
    organization of the account's own type. Conversations, procurement requests
    and quotations of a pending, rejected or suspended organization stay closed
    to its members (404) until it is approved."""
    return list(
        db.scalars(
            select(Membership.organization_id)
            .join(Organization, Organization.organization_id == Membership.organization_id)
            .where(
                Membership.user_id == user.user_id,
                Membership.is_active.is_(True),
                Membership.organization_id.in_(org_ids),
                Organization.status == OrganizationStatus.APPROVED,
                Organization.type == user.account_type,
            )
        )
    )


def load_conversation(
    db: Session, user: User, conversation_id: int, organization_id: int | None = None
) -> tuple[Conversation, int]:
    """The conversation and the organization the user acts for in it.
    404 for anyone who is not an active member of one of the two
    organizations, so other organizations' conversations stay invisible."""
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise NotFound("Conversation not found.")
    sides = [conv.pharmacy_organization_id, conv.supplier_organization_id]
    mine = member_org_ids(db, user, sides)
    if organization_id is not None:
        mine = [o for o in mine if o == organization_id]
    if not mine:
        raise NotFound("Conversation not found.")
    # A user in both organizations (rare) acts for the pharmacy unless told otherwise.
    return conv, conv.pharmacy_organization_id if conv.pharmacy_organization_id in mine else mine[0]


def counterpart_id(conv: Conversation, my_org_id: int) -> int:
    return (
        conv.supplier_organization_id
        if my_org_id == conv.pharmacy_organization_id
        else conv.pharmacy_organization_id
    )


def require_approved(db: Session, *org_ids: int) -> None:
    """Messages, requests and quotations need both organizations approved."""
    for org_id in org_ids:
        status = db.scalar(select(Organization.status).where(Organization.organization_id == org_id))
        if status != OrganizationStatus.APPROVED:
            raise Forbidden("Both organizations must be approved by ApexRx to exchange messages and requests.")


def get_or_create_conversation(
    db: Session, pharmacy_id: int, supplier_id: int, user_id: int
) -> tuple[Conversation, bool]:
    """The pair's single conversation; created if it does not exist yet. Safe
    against two requests creating it at the same time (unique pair)."""
    created = db.execute(
        insert(Conversation)
        .values(
            pharmacy_organization_id=pharmacy_id,
            supplier_organization_id=supplier_id,
            created_by=user_id,
        )
        .on_conflict_do_nothing(constraint="uq_conversation_pair")
        .returning(Conversation.conversation_id)
    ).scalar()
    conv = db.scalar(
        select(Conversation).where(
            Conversation.pharmacy_organization_id == pharmacy_id,
            Conversation.supplier_organization_id == supplier_id,
        )
    )
    return conv, created is not None


def pair_for(my_org: Organization, other_org: Organization) -> tuple[int, int]:
    """(pharmacy_id, supplier_id) for two organizations of opposite types."""
    if my_org.type == other_org.type:
        raise Forbidden("Conversations are between a pharmacy and a supplier.")
    if my_org.type == OrganizationType.PHARMACY:
        return my_org.organization_id, other_org.organization_id
    return other_org.organization_id, my_org.organization_id


def notify(db: Session, organization_id: int, kind: str, from_organization_id: int | None, **refs) -> None:
    db.add(
        Notification(
            organization_id=organization_id,
            kind=kind,
            from_organization_id=from_organization_id,
            **refs,
        )
    )


def notify_reservation(
    db: Session,
    kind: str,
    reservation_id: int,
    *,
    organization_id: int | None = None,
    recipient_user_id: int | None = None,
    from_organization_id: int | None = None,
) -> bool:
    """A reservation event for one pharmacy organization or one patient
    (exactly one of the two). Recorded at most once per event and recipient
    (uq_notification_reservation_event), so a retried transition cannot
    notify twice. Rows carry ids only, never patient details. Returns whether
    a notification was created (False: it already existed)."""
    if (organization_id is None) == (recipient_user_id is None):
        raise ValueError("A notification has exactly one recipient.")
    result = db.execute(
        insert(Notification)
        .values(
            kind=kind,
            reservation_id=reservation_id,
            organization_id=organization_id,
            recipient_user_id=recipient_user_id,
            from_organization_id=from_organization_id,
        )
        .on_conflict_do_nothing()
        .returning(Notification.notification_id)
    )
    return result.first() is not None


def add_message(db: Session, conv: Conversation, my_org_id: int, user: User, body: str) -> ChatMessage:
    message = ChatMessage(
        conversation_id=conv.conversation_id,
        sender_organization_id=my_org_id,
        sender_user_id=user.user_id,
        body=body,
    )
    db.add(message)
    db.flush()
    notify(
        db,
        counterpart_id(conv, my_org_id),
        "message",
        my_org_id,
        conversation_id=conv.conversation_id,
    )
    mark_read(db, conv.conversation_id, my_org_id, user, message.message_id)
    return message


def mark_read(db: Session, conversation_id: int, my_org_id: int, user: User, up_to_message_id: int) -> None:
    """Record that the user has read the conversation up to a message, and
    clear their message notifications for it."""
    stmt = insert(ConversationRead).values(
        conversation_id=conversation_id, user_id=user.user_id, last_read_message_id=up_to_message_id
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ConversationRead.conversation_id, ConversationRead.user_id],
            set_={
                "last_read_message_id": func.greatest(
                    ConversationRead.last_read_message_id, stmt.excluded.last_read_message_id
                ),
                "updated_at": func.now(),
            },
        )
    )
    pending = select(Notification.notification_id, literal(user.user_id)).where(
        Notification.organization_id == my_org_id,
        Notification.conversation_id == conversation_id,
        Notification.kind == "message",
        ~select(NotificationRead.notification_id)
        .where(
            NotificationRead.notification_id == Notification.notification_id,
            NotificationRead.user_id == user.user_id,
        )
        .exists(),
    )
    db.execute(
        insert(NotificationRead)
        .from_select(["notification_id", "user_id"], pending)
        .on_conflict_do_nothing()
    )


def unread_counts(db: Session, user: User, my_org_id: int, conversation_ids: list[int]) -> dict[int, int]:
    """Messages from the other organization the user has not read yet."""
    if not conversation_ids:
        return {}
    rows = db.execute(
        select(ChatMessage.conversation_id, func.count())
        .outerjoin(
            ConversationRead,
            and_(
                ConversationRead.conversation_id == ChatMessage.conversation_id,
                ConversationRead.user_id == user.user_id,
            ),
        )
        .where(
            ChatMessage.conversation_id.in_(conversation_ids),
            ChatMessage.sender_organization_id != my_org_id,
            or_(
                ConversationRead.last_read_message_id.is_(None),
                ChatMessage.message_id > ConversationRead.last_read_message_id,
            ),
        )
        .group_by(ChatMessage.conversation_id)
    ).all()
    return dict(rows)
