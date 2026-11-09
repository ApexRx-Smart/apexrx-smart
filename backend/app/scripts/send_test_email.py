"""Send one real test email through the configured provider (EMAIL_PROVIDER).

    python -m app.scripts.send_test_email --to you@example.com

Uses the same settings as the API (environment, otherwise backend/.env). This
is how to confirm that Gmail API delivery works: email delivery should only be
called operational after this message arrives. Prints the provider's message
id, never credentials.
"""

import argparse
import sys
from datetime import datetime, timezone

from app.core.config import settings
from app.services.email import EmailError, get_email_provider, templates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True)
    args = parser.parse_args()
    try:
        provider = get_email_provider()
    except EmailError as exc:
        print(f"Email is not configured: {exc}", file=sys.stderr)
        return 1
    message = templates._render(
        to=args.to, subject="ApexRX Smart test email", name=None,
        paragraphs=[f"This is a test email from ApexRX Smart ({settings.app_env}), sent "
                    f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC through the {provider.name} provider."],
        notes=["If you received it, email delivery is working."],
    )
    try:
        result = provider.send(message)
    except EmailError as exc:
        print(f"Sending failed: {exc}", file=sys.stderr)
        return 1
    print(f"Accepted by {result.provider}; message id {result.message_id}. Check the inbox of {args.to}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
