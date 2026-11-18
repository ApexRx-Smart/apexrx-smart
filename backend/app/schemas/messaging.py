from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

# Chat text: trimmed, 1 to 4000 characters (the database checks the same).
MessageBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ConversationCreate(BaseModel):
    organization_id: int
    counterpart_organization_id: int


class MessageCreate(BaseModel):
    body: MessageBody


class ReadRequest(BaseModel):
    last_message_id: int


class Counterpart(BaseModel):
    organization_id: int
    name: str
    type: str
    city: str | None = None
    phone: str | None = None


class MessageResponse(BaseModel):
    message_id: int
    conversation_id: int
    sender_organization_id: int
    sender_user_id: int | None
    sender_name: str | None
    mine: bool
    body: str
    created_at: datetime


class ConversationResponse(BaseModel):
    conversation_id: int
    organization_id: int
    counterpart: Counterpart
    created_at: datetime
    last_message_at: datetime | None
    last_message: MessageResponse | None
    unread_count: int


class ConversationList(BaseModel):
    items: list[ConversationResponse]
    unread_total: int


class MessagePage(BaseModel):
    items: list[MessageResponse]
    has_more: bool
    last_read_message_id: int | None


class NotificationResponse(BaseModel):
    notification_id: int
    kind: str
    from_organization_id: int | None
    from_organization_name: str | None
    conversation_id: int | None
    procurement_request_id: int | None
    quotation_id: int | None
    purchase_order_id: int | None
    reservation_reference: str | None = None
    created_at: datetime
    read: bool


class NotificationList(BaseModel):
    items: list[NotificationResponse]
    unread_count: int


class NotificationReadRequest(BaseModel):
    organization_id: int | None = None  # omit for your personal notifications
    notification_ids: list[int] | None = None
    all: bool = False
