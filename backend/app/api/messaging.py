"""In-platform messaging between pharmacies and suppliers, and notifications.

A conversation belongs to a pharmacy and a supplier organization: every
active member of either can read and write in it, and nobody else can see
that it exists (404). Platform admins have no access to these private
conversations. Delivery is by polling: the dashboards ask for messages newer
than the last one they have (``after_id``).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.catalogue import contains
from app.api.deps import CurrentUser, DbSession, get_org_access
from app.core.errors import NotFound, TooManyRequests
from app.core.rate_limit import message_limiter
from app.models import (
    ChatMessage,
    Conversation,
    ConversationRead,
    Location,
    Notification,
    NotificationRead,
    Organization,
    User,
)
from app.models.enums import OrganizationStatus, OrganizationType
from app.schemas.messaging import (
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    Counterpart,
    MessageCreate,
    MessagePage,
    MessageResponse,
    NotificationList,
    NotificationReadRequest,
    NotificationResponse,
    ReadRequest,
)
from app.services import messaging as svc

router = APIRouter()
notifications_router = APIRouter()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def counterparts(db: Session, organization_ids: set[int]) -> dict[int, Counterpart]:
    """Name, type, phone and a city (first active location with one) per organization."""
    if not organization_ids:
        return {}
    cities = dict(
        db.execute(
            select(Location.organization_id, Location.city)
            .where(Location.organization_id.in_(organization_ids), Location.is_active.is_(True),
                   Location.city.isnot(None))
            .distinct(Location.organization_id)
            .order_by(Location.organization_id, Location.location_id)
        ).all()
    )
    orgs = db.scalars(select(Organization).where(Organization.organization_id.in_(organization_ids))).all()
    return {
        o.organization_id: Counterpart(organization_id=o.organization_id, name=o.name, type=o.type,
                                       city=cities.get(o.organization_id), phone=o.phone)
        for o in orgs
    }


def messages_out(db: Session, rows: list[ChatMessage], my_org_id: int) -> list[MessageResponse]:
    names = dict(
        db.execute(
            select(User.user_id, User.name).where(User.user_id.in_({m.sender_user_id for m in rows if m.sender_user_id}))
        ).all()
    )
    return [
        MessageResponse(
            message_id=m.message_id,
            conversation_id=m.conversation_id,
            sender_organization_id=m.sender_organization_id,
            sender_user_id=m.sender_user_id,
            sender_name=names.get(m.sender_user_id),
            mine=m.sender_organization_id == my_org_id,
            body=m.body,
            created_at=m.created_at,
        )
        for m in rows
    ]


def conversations_out(db: Session, user: User, convs: list[Conversation], my_org_id: int) -> list[ConversationResponse]:
    """Serialize conversations with a fixed number of queries (the list is polled)."""
    ids = [c.conversation_id for c in convs]
    if not ids:
        return []
    unread = svc.unread_counts(db, user, my_org_id, ids)
    last_rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id.in_(ids))
        .distinct(ChatMessage.conversation_id)
        .order_by(ChatMessage.conversation_id, ChatMessage.message_id.desc())
    ).all()
    last = {m.conversation_id: m for m in messages_out(db, last_rows, my_org_id)}
    parties = counterparts(db, {svc.counterpart_id(c, my_org_id) for c in convs})
    return [
        ConversationResponse(
            conversation_id=c.conversation_id,
            organization_id=my_org_id,
            counterpart=parties[svc.counterpart_id(c, my_org_id)],
            created_at=c.created_at,
            last_message_at=c.last_message_at,
            last_message=last.get(c.conversation_id),
            unread_count=unread.get(c.conversation_id, 0),
        )
        for c in convs
    ]


def conversation_out(db: Session, user: User, conv: Conversation, my_org_id: int) -> ConversationResponse:
    return conversations_out(db, user, [conv], my_org_id)[0]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
@router.get("", response_model=ConversationList)
def list_conversations(
    user: CurrentUser,
    db: DbSession,
    organization_id: Annotated[int, Query(description="Your pharmacy or supplier organization")],
):
    """The organization's conversations, most recent activity first, with the
    last message and the number of messages this user has not read."""
    access = get_org_access(db, user, organization_id)
    own = (
        Conversation.pharmacy_organization_id
        if access.organization.type == OrganizationType.PHARMACY
        else Conversation.supplier_organization_id
    )
    convs = db.scalars(
        select(Conversation)
        .where(own == organization_id)
        .order_by(func.coalesce(Conversation.last_message_at, Conversation.created_at).desc())
        .limit(200)
    ).all()
    items = conversations_out(db, user, list(convs), organization_id)
    return ConversationList(items=items, unread_total=sum(c.unread_count for c in items))


@router.post("", response_model=ConversationResponse)
def start_conversation(payload: ConversationCreate, user: CurrentUser, db: DbSession, response: Response):
    """Open the conversation with a pharmacy (for a supplier) or a supplier
    (for a pharmacy). If the two already have one, it is returned (200)
    instead of creating a duplicate (201)."""
    access = get_org_access(db, user, payload.organization_id, require_approved=True)
    other = db.get(Organization, payload.counterpart_organization_id)
    if other is None or other.status != OrganizationStatus.APPROVED or other.type == access.organization.type:
        raise NotFound("Organization not found.")
    pharmacy_id, supplier_id = svc.pair_for(access.organization, other)
    conv, created = svc.get_or_create_conversation(db, pharmacy_id, supplier_id, user.user_id)
    db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return conversation_out(db, user, conv, payload.organization_id)


@router.get("/contacts", response_model=list[Counterpart])
def contacts(
    user: CurrentUser,
    db: DbSession,
    organization_id: int,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """Approved organizations of the other type this organization can write
    to: suppliers for a pharmacy, pharmacies for a supplier."""
    access = get_org_access(db, user, organization_id)
    other_type = (
        OrganizationType.SUPPLIER
        if access.organization.type == OrganizationType.PHARMACY
        else OrganizationType.PHARMACY
    )
    stmt = select(Organization.organization_id).where(
        Organization.type == other_type, Organization.status == OrganizationStatus.APPROVED
    )
    if q and q.strip():
        stmt = stmt.where(Organization.name.ilike(contains(q.strip()), escape="\\"))
    ids = db.scalars(stmt.order_by(Organization.name).limit(20)).all()
    found = counterparts(db, set(ids))
    return [found[i] for i in ids]


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: int, user: CurrentUser, db: DbSession, organization_id: int | None = None):
    conv, mine = svc.load_conversation(db, user, conversation_id, organization_id)
    return conversation_out(db, user, conv, mine)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
def list_messages(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
    organization_id: int | None = None,
    after_id: Annotated[int | None, Query(description="Only messages newer than this one (polling)")] = None,
    before_id: Annotated[int | None, Query(description="Older history, before this message")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """Messages in chronological order: the latest ``limit`` by default,
    newer than ``after_id`` when polling, or older than ``before_id``."""
    conv, mine = svc.load_conversation(db, user, conversation_id, organization_id)
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conv.conversation_id)
    if after_id is not None:
        rows = db.scalars(stmt.where(ChatMessage.message_id > after_id).order_by(ChatMessage.message_id).limit(limit + 1)).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
    else:
        if before_id is not None:
            stmt = stmt.where(ChatMessage.message_id < before_id)
        rows = db.scalars(stmt.order_by(ChatMessage.message_id.desc()).limit(limit + 1)).all()
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
    read = db.scalar(
        select(ConversationRead.last_read_message_id).where(
            ConversationRead.conversation_id == conv.conversation_id, ConversationRead.user_id == user.user_id
        )
    )
    return MessagePage(items=messages_out(db, rows, mine), has_more=has_more, last_read_message_id=read)


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(conversation_id: int, payload: MessageCreate, user: CurrentUser, db: DbSession,
                 organization_id: int | None = None):
    """Send a message. Both organizations must be approved; at most 30
    messages a minute per user (429 with Retry-After beyond that)."""
    conv, mine = svc.load_conversation(db, user, conversation_id, organization_id)
    svc.require_approved(db, conv.pharmacy_organization_id, conv.supplier_organization_id)
    wait = message_limiter.hit(str(user.user_id))
    if wait is not None:
        raise TooManyRequests(
            "You are sending messages too quickly. Please wait a moment and try again.",
            headers={"Retry-After": str(wait)},
        )
    message = svc.add_message(db, conv, mine, user, payload.body)
    db.commit()
    return messages_out(db, [message], mine)[0]


@router.post("/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(conversation_id: int, payload: ReadRequest, user: CurrentUser, db: DbSession,
              organization_id: int | None = None):
    """Record that this user has read the conversation up to a message."""
    conv, mine = svc.load_conversation(db, user, conversation_id, organization_id)
    exists = db.scalar(
        select(ChatMessage.message_id).where(
            ChatMessage.conversation_id == conv.conversation_id, ChatMessage.message_id == payload.last_message_id
        )
    )
    if exists is None:
        raise NotFound("Message not found in this conversation.")
    svc.mark_read(db, conv.conversation_id, mine, user, payload.last_message_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def _is_read(user: User):
    return (
        select(NotificationRead.notification_id)
        .where(NotificationRead.notification_id == Notification.notification_id, NotificationRead.user_id == user.user_id)
        .exists()
    )


@notifications_router.get("", response_model=NotificationList)
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    organization_id: int,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
):
    """The organization's latest notifications (visible to all its active
    members), each marked read or unread for this user."""
    get_org_access(db, user, organization_id)
    read = _is_read(user)
    rows = db.execute(
        select(Notification, read.label("read"))
        .where(Notification.organization_id == organization_id)
        .order_by(Notification.notification_id.desc())
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(Notification.organization_id == organization_id, ~read)
    )
    names = dict(
        db.execute(
            select(Organization.organization_id, Organization.name).where(
                Organization.organization_id.in_({n.from_organization_id for n, _ in rows if n.from_organization_id})
            )
        ).all()
    )
    return NotificationList(
        items=[
            NotificationResponse(
                notification_id=n.notification_id,
                kind=n.kind,
                from_organization_id=n.from_organization_id,
                from_organization_name=names.get(n.from_organization_id),
                conversation_id=n.conversation_id,
                procurement_request_id=n.procurement_request_id,
                quotation_id=n.quotation_id,
                purchase_order_id=n.purchase_order_id,
                created_at=n.created_at,
                read=is_read,
            )
            for n, is_read in rows
        ],
        unread_count=unread,
    )


@notifications_router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
def read_notifications(payload: NotificationReadRequest, user: CurrentUser, db: DbSession):
    """Mark some (``notification_ids``) or all (``all``) of the organization's
    notifications as read for this user."""
    get_org_access(db, user, payload.organization_id)
    stmt = select(Notification.notification_id, literal(user.user_id)).where(
        Notification.organization_id == payload.organization_id
    )
    if not payload.all:
        stmt = stmt.where(Notification.notification_id.in_(payload.notification_ids or []))
    db.execute(insert(NotificationRead).from_select(["notification_id", "user_id"], stmt).on_conflict_do_nothing())
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
