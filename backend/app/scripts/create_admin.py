"""Create a platform administrator, or promote an existing user.

    python -m app.scripts.create_admin --email admin@apexrx.rw --name "ApexRx Admin"

The target database is DATABASE_URL from the environment, otherwise from
backend/.env. The script shows which host and database it will write to and
asks for confirmation (skip with --yes).

* If the email already has an account, it is promoted to platform admin and
  reactivated. Its password is not changed.
* Otherwise a new account is created. The password is prompted for, hidden
  (or read from APEXRX_ADMIN_PASSWORD).
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="ApexRx Admin")
    parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    args = parser.parse_args()
    email = args.email.strip().lower()

    url = make_url(settings.database_url)
    target = f"{url.host or 'localhost'}/{url.database}"  # never print the password
    print(f"Target database: {target}")
    if not args.yes and input(f"Make {email} a platform admin on {target}? Type 'yes' to continue: ") != "yes":
        print("Cancelled. Nothing was changed.")
        return 1

    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(func.btrim(User.email)) == email))
        if user is not None:
            user.is_platform_admin = True
            user.is_active = True
            db.commit()
            print(f"Promoted existing user {email} (user_id {user.user_id}) to platform admin.")
            return 0

        password = os.environ.get("APEXRX_ADMIN_PASSWORD") or getpass.getpass("Password (min 8 chars): ")
        if len(password) < 8:
            print("Password must be at least 8 characters.", file=sys.stderr)
            return 1
        user = User(
            name=args.name,
            email=email,
            password_hash=hash_password(password),
            is_platform_admin=True,
        )
        db.add(user)
        db.commit()
        print(f"Created platform admin {email} (user_id {user.user_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
