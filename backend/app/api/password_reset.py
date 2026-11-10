"""Forgot password (see app/services/password_reset.py).

  POST /auth/password/forgot        {email}               same 202 answer whether or not the account exists
  POST /auth/password/reset/check   {token}               is the link still usable? (masked email)
  POST /auth/password/reset         {token, new_password} set the new password; signs out every session
"""

from fastapi import APIRouter, BackgroundTasks, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import DbSession
from app.core.rate_limit import client_ip
from app.core.security import hash_password
from app.schemas.common import Message
from app.services import account_emails, password_reset
from app.services.email_verification import mask_email

router = APIRouter()


class ForgotRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetRequest(TokenRequest):
    new_password: str = Field(min_length=8, max_length=128)


class ResetCheck(BaseModel):
    valid: bool = True
    email_masked: str


@router.post("/forgot", response_model=Message, status_code=status.HTTP_202_ACCEPTED,
             responses={429: {"description": "Too many requests for this address or from this IP"}})
def forgot_password(payload: ForgotRequest, request: Request, db: DbSession, background: BackgroundTasks):
    password_reset.request_reset(db, str(payload.email), client_ip(request), background)
    return Message(detail=password_reset.PUBLIC_MESSAGE)


@router.post("/reset/check", response_model=ResetCheck)
def check_reset_link(payload: TokenRequest, db: DbSession):
    """Errors carry a ``reason``: invalid, used, superseded, expired."""
    user = password_reset.check(db, payload.token)
    return ResetCheck(email_masked=mask_email(user.email))


@router.post("/reset", response_model=Message)
def reset_password(payload: ResetRequest, db: DbSession, background: BackgroundTasks):
    user = password_reset.complete(db, payload.token, hash_password(payload.new_password))
    background.add_task(account_emails.send_password_changed, user.user_id)
    return Message(detail="Your password has been changed. Sign in with your new password.")
