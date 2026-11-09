"""Staff invitations: an owner or manager invites an email address with a role;
the person who controls that address accepts, with a new account or their
existing one, and only then does the membership exist.

Tokens
* 32 random bytes (``secrets``), URL-safe, in the fragment of
  <FRONTEND_BASE_URL>/accept-invitation.html#token=... (never sent to a server
  in a request line or Referer). Only a SHA-256 hash is stored.
* One usable link per invitation: resending replaces the hash, so the earlier
  email's link stops working. Single use: an accepted invitation is closed.
* Valid for INVITATION_TTL_HOURS (default 72); a resend starts a new period.
* Bound to the organization and to the invited address: an account with a
  different email can never accept it.

States, kept apart on purpose: created (row) -> sent (the provider accepted the
email; a failure is recorded and can be retried, nothing is activated) ->
accepted (membership created or reactivated, account created or linked).
Revoked and expired invitations can no longer be accepted.

While email delivery is disabled (no provider; see app/services/email), no
email is attempted: the link is returned ONCE to the owner or manager who
created (or renewed) it, to pass on to the employee themselves, and the
invitation's delivery is "link". Accepting such a link does not mark the email
address verified, because nobody proved control of the mailbox.
"""

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, Conflict, Forbidden, TooManyRequests
from app.models import Membership, Organization, OrganizationInvitation, User
from app.models.enums import MembershipRole
from app.services.email import (
    EmailDeliveryError,
    EmailNotConfigured,
    email_delivery_available,
    get_email_provider,
    templates,
)

logger = logging.getLogger("apexrx.invitations")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class InvitationRejected(AppError):
    status_code = status.HTTP_400_BAD_REQUEST


def now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return str(email).strip().lower()


def mask_email(email: str) -> str:
    local, _, domain = normalize_email(email).partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def state(inv: OrganizationInvitation, at: datetime | None = None) -> str:
    if inv.accepted_at is not None:
        return "accepted"
    if inv.revoked_at is not None:
        return "revoked"
    if inv.expires_at <= (at or now()):
        return "expired"
    return "pending"


def delivery(inv: OrganizationInvitation) -> str:
    """How the current link reached the invitee: sent (emailed), failed (email
    refused), link (shared by the inviter; email disabled) or not_sent."""
    if inv.sent_at is not None:
        return "sent"
    if inv.send_failed_at is not None:
        return "failed"
    return "not_sent" if email_delivery_available() else "link"


def _new_token(inv: OrganizationInvitation) -> str:
    """A new link: the previous one stops working, a new validity period
    starts, and the delivery state restarts (it describes the current link)."""
    token = secrets.token_urlsafe(32)
    inv.token_hash = hash_token(token)
    inv.expires_at = now() + timedelta(hours=settings.invitation_ttl_hours)
    inv.sent_at = None
    inv.send_failed_at = None
    return token


# ---------------------------------------------------------------------------
# Inviting (owners and managers; the caller checks the role)
# ---------------------------------------------------------------------------
def create(db: Session, organization: Organization, inviter: User, email: str, role: MembershipRole) -> tuple[OrganizationInvitation, str]:
    email = normalize_email(email)
    member = db.execute(
        select(Membership).join(User, User.user_id == Membership.user_id).where(
            Membership.organization_id == organization.organization_id,
            Membership.is_active.is_(True),
            func.lower(func.btrim(User.email)) == email,
        )
    ).scalar_one_or_none()
    if member is not None:
        raise Conflict("This person is already a member of the organization.", extra={"reason": "already_member"})

    t = now()
    recent = db.scalar(
        select(func.count()).select_from(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization.organization_id,
            OrganizationInvitation.created_at > t - timedelta(hours=1),
        )
    )
    if recent >= settings.invitation_max_per_organization_per_hour:
        raise TooManyRequests("Too many invitations this hour. Please try again later.",
                              headers={"Retry-After": "3600"}, extra={"retry_after": 3600})

    open_inv = db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == organization.organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.accepted_at.is_(None),
            OrganizationInvitation.revoked_at.is_(None),
        ).with_for_update()
    )
    if open_inv is not None:
        if state(open_inv, t) == "pending":
            raise Conflict("This email already has a pending invitation. Resend it instead.",
                           extra={"reason": "already_invited", "invitation_id": open_inv.invitation_id})
        open_inv.revoked_at = t  # expired: replaced by the new invitation
        open_inv.revoked_by = inviter.user_id
        db.flush()

    inv = OrganizationInvitation(
        organization_id=organization.organization_id, email=email, role=role.value,
        invited_by=inviter.user_id, created_at=t, token_hash="pending",
    )
    token = _new_token(inv)
    db.add(inv)
    db.commit()
    return inv, token


@dataclass(frozen=True)
class SendOutcome:
    sent: bool
    message: str
    share_token: str | None = None  # only when email is disabled: for the inviter to pass on


def deliver(db: Session, inv: OrganizationInvitation, token: str) -> SendOutcome:
    """Email the invitation, or (email disabled) hand the link to the inviter."""
    if not email_delivery_available():
        db.commit()
        return SendOutcome(False, "Email is temporarily unavailable, so no email was sent. Copy the invitation "
                                  "link below and give it to the employee yourself (for example by WhatsApp). "
                                  "Anyone with the link can use it to join, so share it only with them.",
                           share_token=token)
    return send(db, inv, token)


def send(db: Session, inv: OrganizationInvitation, token: str) -> SendOutcome:
    """Email the invitation. Records success or failure; never raises for a
    delivery problem (the invitation stays and can be resent)."""
    organization = db.get(Organization, inv.organization_id)
    inviter = db.get(User, inv.invited_by) if inv.invited_by else None
    message = templates.invitation(
        to=inv.email, organization=organization.name, role=inv.role,
        inviter=inviter.name if inviter else None,
        url=templates.link("accept-invitation.html", token),
        expires_minutes=settings.invitation_ttl_hours * 60,
    )
    try:
        get_email_provider().send(message)
    except EmailNotConfigured as exc:
        logger.error("Invitation %s not sent: email is not configured (%s)", inv.invitation_id, exc)
        inv.send_failed_at = now()
        db.commit()
        return SendOutcome(False, "The invitation is saved, but email is not configured on the server, so it "
                                  "was not sent. Try “Resend” once email works.")
    except Exception as exc:  # noqa: BLE001 - any provider problem is a failed delivery
        reason = str(exc) if isinstance(exc, EmailDeliveryError) else type(exc).__name__
        logger.error("Invitation %s email to %s failed: %s", inv.invitation_id, mask_email(inv.email), reason)
        inv.send_failed_at = now()
        db.commit()
        return SendOutcome(False, "The invitation is saved, but the email could not be sent. Try “Resend” in a moment.")
    inv.sent_at = now()
    inv.send_count += 1
    db.commit()
    logger.info("Invitation %s sent to %s", inv.invitation_id, mask_email(inv.email))
    return SendOutcome(True, f"Invitation emailed to {inv.email}.")


def resend(db: Session, inv: OrganizationInvitation) -> SendOutcome:
    """A new link (the earlier one stops working), emailed or handed to the inviter."""
    if state(inv) in ("accepted", "revoked"):
        raise Conflict(f"This invitation was {state(inv)} and cannot be resent.")
    cooldown = settings.invitation_resend_cooldown_seconds
    if cooldown and inv.sent_at is not None and delivery(inv) == "sent" and state(inv) == "pending":
        wait = cooldown - (now() - inv.sent_at).total_seconds()
        if wait > 0:
            raise TooManyRequests(f"Please wait {int(wait) + 1} seconds before resending.",
                                  headers={"Retry-After": str(int(wait) + 1)}, extra={"retry_after": int(wait) + 1})
    token = _new_token(inv)  # the earlier link stops working; a new validity period starts
    db.commit()
    return deliver(db, inv, token)


def revoke(db: Session, inv: OrganizationInvitation, by: User) -> None:
    if inv.accepted_at is not None:
        raise Conflict("This invitation was already accepted; remove the member instead.")
    if inv.revoked_at is None:
        inv.revoked_at = now()
        inv.revoked_by = by.user_id
    db.commit()


# ---------------------------------------------------------------------------
# Accepting (public link)
# ---------------------------------------------------------------------------
def by_token(db: Session, token: str, *, lock: bool = False) -> OrganizationInvitation:
    """The usable invitation for ``token``, or InvitationRejected with a reason."""
    token = (token or "").strip()
    if not _TOKEN.match(token):
        raise InvitationRejected("This invitation link is not valid.", extra={"reason": "invalid"})
    stmt = select(OrganizationInvitation).where(OrganizationInvitation.token_hash == hash_token(token))
    inv = db.scalar(stmt.with_for_update() if lock else stmt)
    if inv is None:
        raise InvitationRejected("This invitation link is not valid. It may have been replaced by a newer email.",
                                 extra={"reason": "invalid"})
    current = state(inv)
    if current == "accepted":
        raise InvitationRejected("This invitation has already been accepted. Sign in to continue.",
                                 extra={"reason": "used"})
    if current == "revoked":
        raise InvitationRejected("This invitation was withdrawn. Ask the pharmacy for a new one.",
                                 extra={"reason": "revoked"})
    if current == "expired":
        raise InvitationRejected("This invitation has expired. Ask the pharmacy to send it again.",
                                 extra={"reason": "expired"})
    return inv


def find_account(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(func.btrim(User.email)) == normalize_email(email)))


def _activate(db: Session, inv: OrganizationInvitation, user: User, *, account_created: bool) -> Membership:
    """Create or reactivate the membership with the invited role and close the
    invitation. An existing active membership keeps its role."""
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == inv.organization_id, Membership.user_id == user.user_id
    ).with_for_update())
    if membership is None:
        membership = Membership(user_id=user.user_id, organization_id=inv.organization_id, role=inv.role)
        db.add(membership)
    elif not membership.is_active:
        membership.is_active = True
        membership.role = inv.role
    t = now()
    inv.accepted_at = t
    inv.accepted_by = user.user_id
    inv.account_created = account_created
    if user.email_verified_at is None and inv.sent_at is not None:
        user.email_verified_at = t  # opening the EMAILED link proved control of the address
    db.flush()
    return membership


def accept_with_new_account(db: Session, token: str, name: str, password_hash: str) -> tuple[User, OrganizationInvitation, Membership]:
    inv = by_token(db, token, lock=True)
    if find_account(db, inv.email) is not None:
        db.rollback()
        raise Conflict("An ApexRX account already uses this email. Sign in to accept the invitation.",
                       extra={"reason": "account_exists"})
    user = User(name=name, email=inv.email, password_hash=password_hash)
    db.add(user)
    db.flush()
    membership = _activate(db, inv, user, account_created=True)
    db.commit()
    return user, inv, membership


def accept_with_account(db: Session, token: str, user: User) -> tuple[OrganizationInvitation, Membership]:
    inv = by_token(db, token, lock=True)
    if normalize_email(user.email) != inv.email:
        db.rollback()
        raise Forbidden(f"This invitation was sent to {mask_email(inv.email)}. Sign in with that account to accept it.",
                        extra={"reason": "email_mismatch"})
    membership = _activate(db, inv, user, account_created=False)
    db.commit()
    return inv, membership
