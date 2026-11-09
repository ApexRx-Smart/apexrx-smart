"""The Gmail API adapter, with Google's endpoints replaced (no network):
OAuth refresh, token caching, the RFC 822 message, retry on 401, and errors
that never contain secrets."""

import base64
import email

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services.email import EmailDeliveryError, EmailMessage, EmailNotConfigured, get_email_provider
from app.services.email import gmail as gmail_module
from app.services.email.gmail import SEND_URL, TOKEN_URL, GmailProvider

MESSAGE = EmailMessage(to="staff@example.com", subject="Hello", text="Plain text body", html="<p>HTML body</p>")


class FakeGoogle:
    def __init__(self, token_status=200, send_statuses=(200,), token_error="invalid_grant"):
        self.token_status, self.send_statuses, self.token_error = token_status, list(send_statuses), token_error
        self.calls = []

    def __call__(self, url, data=None, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "json": json, "headers": headers})
        request = httpx.Request("POST", url)
        if url == TOKEN_URL:
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": self.token_error,
                                                               "error_description": "Token has been expired or revoked."},
                                      request=request)
            return httpx.Response(200, json={"access_token": f"ya29.access-{len(self.calls)}", "expires_in": 3599,
                                             "scope": "https://www.googleapis.com/auth/gmail.send"}, request=request)
        status = self.send_statuses.pop(0) if self.send_statuses else 200
        if status >= 300:
            return httpx.Response(status, json={"error": {"code": status, "status": "UNAUTHENTICATED"}}, request=request)
        return httpx.Response(200, json={"id": "18c0ffee", "threadId": "18c0ffee"}, request=request)


def _provider():
    return GmailProvider("client-id.apps.googleusercontent.com", "client-secret-value", "1//refresh-token-value",
                         "ApexRX Smart", "apexrx.team@gmail.com")


def test_sends_through_the_gmail_api(monkeypatch):
    google = FakeGoogle()
    monkeypatch.setattr(httpx, "post", google)
    provider = _provider()
    assert provider.send(MESSAGE).message_id == "18c0ffee"
    token_call, send_call = google.calls
    assert token_call["data"] == {"client_id": "client-id.apps.googleusercontent.com",
                                  "client_secret": "client-secret-value",
                                  "refresh_token": "1//refresh-token-value", "grant_type": "refresh_token"}
    assert send_call["url"] == SEND_URL and send_call["headers"]["Authorization"] == "Bearer ya29.access-1"
    mime = email.message_from_bytes(base64.urlsafe_b64decode(send_call["json"]["raw"]))
    assert mime["To"] == "staff@example.com" and mime["Subject"] == "Hello"
    assert mime["From"] == "ApexRX Smart <apexrx.team@gmail.com>"
    parts = {p.get_content_type(): p.get_payload(decode=True).decode() for p in mime.walk() if not p.is_multipart()}
    assert "Plain text body" in parts["text/plain"] and "<p>HTML body</p>" in parts["text/html"]
    # The access token is reused for the next message.
    provider.send(MESSAGE)
    assert [c["url"] for c in google.calls] == [TOKEN_URL, SEND_URL, SEND_URL]


def test_refreshes_once_on_401(monkeypatch):
    google = FakeGoogle(send_statuses=(401, 200))
    monkeypatch.setattr(httpx, "post", google)
    assert _provider().send(MESSAGE).message_id == "18c0ffee"
    assert [c["url"] for c in google.calls] == [TOKEN_URL, SEND_URL, TOKEN_URL, SEND_URL]


def test_revoked_refresh_token_is_a_failed_delivery(monkeypatch):
    monkeypatch.setattr(httpx, "post", FakeGoogle(token_status=400))
    with pytest.raises(EmailDeliveryError) as info:
        _provider().send(MESSAGE)
    text = str(info.value)
    assert "invalid_grant" in text
    for secret in ("client-secret-value", "1//refresh-token-value", "ya29"):
        assert secret not in text


@pytest.mark.parametrize("statuses", [(403,), (500,), (401, 401)])
def test_send_errors_raise(monkeypatch, statuses):
    monkeypatch.setattr(httpx, "post", FakeGoogle(send_statuses=statuses))
    with pytest.raises(EmailDeliveryError) as info:
        _provider().send(MESSAGE)
    assert str(info.value).startswith("gmail: ") and "ya29" not in str(info.value)


def test_network_error_raises(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(EmailDeliveryError):
        _provider().send(MESSAGE)


def test_selected_by_settings(monkeypatch):
    monkeypatch.setattr(gmail_module, "_instances", {})
    monkeypatch.setattr(settings, "email_provider", "gmail")
    monkeypatch.setattr(settings, "gmail_client_id", None)
    monkeypatch.setattr(settings, "gmail_client_secret", None)
    monkeypatch.setattr(settings, "gmail_refresh_token", None)
    monkeypatch.setattr(settings, "email_from_address", None)
    with pytest.raises(EmailNotConfigured) as info:
        get_email_provider()
    assert "GMAIL_CLIENT_ID" in str(info.value) and "GMAIL_REFRESH_TOKEN" in str(info.value)
    monkeypatch.setattr(settings, "gmail_client_id", "id")
    monkeypatch.setattr(settings, "gmail_client_secret", SecretStr("secret"))
    monkeypatch.setattr(settings, "gmail_refresh_token", SecretStr("refresh"))
    monkeypatch.setattr(settings, "email_from_address", "apexrx.team@gmail.com")
    first, second = get_email_provider(), get_email_provider()
    assert isinstance(first, GmailProvider) and first is second  # shared, so the access token is reused
