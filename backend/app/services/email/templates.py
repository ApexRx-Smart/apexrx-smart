"""ApexRX email templates: one branded layout, plain text and HTML.

Every workflow builds its message here and sends it through
app.services.email.get_email_provider(), so the provider (Gmail API, Resend,
Brevo) can change without touching the workflows. Links always come from
FRONTEND_BASE_URL (never a hard-coded host).
"""

from html import escape

from app.core.config import settings
from app.services.email import EmailMessage

BRAND_GREEN = "#1f8f55"
BRAND_NAVY = "#0f1a3d"


def link(page: str, token: str, query: str = "") -> str:
    """<FRONTEND_BASE_URL>/<page>[?query]#token=<token>. The token sits in the
    fragment, so browsers never send it to a server or in a Referer."""
    return f"{settings.frontend_base_url}/{page}{('?' + query) if query else ''}#token={token}"


def duration(minutes: int) -> str:
    if minutes % (24 * 60) == 0 and minutes >= 48 * 60:
        days = minutes // (24 * 60)
        return f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{minutes} minutes"


def _render(*, to: str, subject: str, name: str | None, paragraphs: list[str],
            button: tuple[str, str] | None = None, notes: list[str] | None = None) -> EmailMessage:
    hello = f"Hello {(name or '').strip() or 'there'},"
    notes = notes or []
    text_parts = [hello, "", *[p for para in paragraphs for p in (para, "")]]
    if button:
        text_parts += [f"{button[0]}:", button[1], ""]
    text_parts += notes
    text_body = "\n".join(text_parts).rstrip() + "\n\nApexRX Smart\n"

    html = [
        f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:{BRAND_NAVY};line-height:1.5;max-width:560px">',
        f'<p style="font-size:18px;font-weight:bold;margin:0 0 18px">ApexRX<span style="color:{BRAND_GREEN}"> Smart</span></p>',
        f"<p>{escape(hello)}</p>",
        *[f"<p>{escape(p)}</p>" for p in paragraphs],
    ]
    if button:
        url = escape(button[1], quote=True)
        html += [
            f'<p><a href="{url}" style="display:inline-block;background:{BRAND_GREEN};color:#ffffff;'
            f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">{escape(button[0])}</a></p>',
            f'<p style="font-size:13px;color:#555">Or open this link: <a href="{url}">{escape(button[1])}</a></p>',
        ]
    html += [f'<p style="font-size:13px;color:#555">{escape(n)}</p>' for n in notes]
    html.append('<p style="font-size:12px;color:#888;margin-top:24px">ApexRX Smart · Smarter access. Better health.</p></div>')
    return EmailMessage(to=to, subject=subject, text=text_body, html="".join(html))


def verification(*, to: str, name: str | None, url: str, expires_minutes: int) -> EmailMessage:
    return _render(
        to=to, subject="Verify your email for ApexRX Smart", name=name,
        paragraphs=["Confirm this email address to continue registering on ApexRX Smart."],
        button=("Verify my email", url),
        notes=[f"The link works once and expires in {duration(expires_minutes)}.",
               "If you did not create an ApexRX Smart account, you can ignore this email."],
    )


ROLE_NAMES = {"owner": "an owner", "manager": "a manager", "staff": "a staff member"}


def invitation(*, to: str, organization: str, role: str, inviter: str | None, url: str,
               expires_minutes: int) -> EmailMessage:
    who = f"{inviter} invited you" if inviter else "You have been invited"
    return _render(
        to=to, subject=f"You're invited to join {organization} on ApexRX Smart", name=None,
        paragraphs=[
            f"{who} to join {organization} on ApexRX Smart as {ROLE_NAMES.get(role, role)}.",
            "Open the invitation to set up your own password, or to sign in if you already have an "
            "ApexRX account with this email address. You will use your own personal account: never share "
            "passwords with colleagues.",
        ],
        button=("Accept the invitation", url),
        notes=[f"The invitation works once and expires in {duration(expires_minutes)}.",
               "If you were not expecting this invitation, you can ignore this email."],
    )


def password_reset(*, to: str, name: str | None, url: str, expires_minutes: int) -> EmailMessage:
    return _render(
        to=to, subject="Reset your ApexRX Smart password", name=name,
        paragraphs=["Someone (hopefully you) asked to reset the password of your ApexRX Smart account."],
        button=("Choose a new password", url),
        notes=[f"The link works once and expires in {duration(expires_minutes)}.",
               "If you did not ask for this, ignore this email: your password stays the same."],
    )


def password_changed(*, to: str, name: str | None) -> EmailMessage:
    return _render(
        to=to, subject="Your ApexRX Smart password was changed", name=name,
        paragraphs=["The password of your ApexRX Smart account was just changed, and your other "
                    "sign-ins were signed out."],
        notes=["If this was not you, reset your password straight away from the sign-in page "
               "(\"Forgot password?\") and contact ApexRX."],
    )
