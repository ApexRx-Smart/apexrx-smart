"""Create a platform administrator, or deliberately promote an existing user.

    python -m app.scripts.create_admin --email admin@apexrx.rw --name "ApexRx Admin"

Target: the database in DATABASE_URL (environment first, otherwise
backend/.env). The script prints the host and database name (never
credentials). For any non-local or production-like database you must retype
the exact host, even with --yes.

* New email: a new platform admin is created. The password is prompted for,
  hidden, twice (or read from APEXRX_ADMIN_PASSWORD).
* Existing email: the account is shown (id, name, status, organizations) and
  nothing changes unless you pass the matching flag:
      --promote-existing   grant platform admin to this existing account
      --reactivate         reactivate this account if it is deactivated
  An existing account's password is never changed.

All checks and confirmations happen before anything is written.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Membership, Organization, User
from app.scripts import safety

MIN_PASSWORD_LENGTH = 8


def _confirm(prompt: str, input_fn) -> bool:
    return input_fn(f"{prompt} Type 'yes' to continue: ").strip() == "yes"


def _describe(db, user: User) -> None:
    rows = db.execute(
        select(Organization.name, Organization.type, Membership.role, Membership.is_active)
        .join(Membership, Membership.organization_id == Organization.organization_id)
        .where(Membership.user_id == user.user_id)
        .order_by(Organization.name)
    ).all()
    print("An account with this email ALREADY EXISTS:")
    print(f"  user_id:         {user.user_id}")
    print(f"  name:            {user.name}")
    print(f"  active:          {'yes' if user.is_active else 'NO (deactivated)'}")
    print(f"  platform admin:  {'yes' if user.is_platform_admin else 'no'}")
    if rows:
        print("  organizations:")
        for name, type_, role, active in rows:
            print(f"    - {name} ({type_}), {role}{'' if active else ', membership inactive'}")
    else:
        print("  organizations:   none")


def main(argv: list[str] | None = None, input_fn=input, getpass_fn=getpass.getpass) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="ApexRx Admin")
    parser.add_argument("--promote-existing", action="store_true", help="Grant admin to an EXISTING account")
    parser.add_argument(
        "--reactivate", action="store_true", help="Reactivate an existing DEACTIVATED account"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the final yes/no prompt (not the host check)"
    )
    args = parser.parse_args(argv)
    email = args.email.strip().lower()
    if "@" not in email:
        print("That does not look like an email address.", file=sys.stderr)
        return 1

    target = safety.current_target()
    print(f"Target database: {target.label}")
    if not target.is_safe_local:
        for reason in target.reasons():
            print(f"Caution: {reason}.")
        if not safety.confirm_host(target, input_fn):
            print("Host did not match. Cancelled; nothing was changed.")
            return 1

    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(func.btrim(User.email)) == email))

        if user is not None:
            _describe(db, user)
            changes = []
            if not user.is_platform_admin:
                if not args.promote_existing:
                    print(
                        "Not changed. To make this existing account a platform admin, re-run with --promote-existing."
                    )
                    return 1
                changes.append("grant platform admin")
            if not user.is_active:
                if not args.reactivate:
                    print(
                        "Not changed. This account is deactivated; re-run with --reactivate to reactivate it."
                    )
                    return 1
                changes.append("reactivate the account")
            if not changes:
                print("This account is already an active platform admin. Nothing was changed.")
                return 0
            print(f"Will: {' and '.join(changes)} for user_id {user.user_id} on {target.label}.")
            print("The account's password will NOT be changed.")
            if not args.yes and not _confirm("Proceed?", input_fn):
                print("Cancelled. Nothing was changed.")
                return 1
            user.is_platform_admin = True
            user.is_active = True
            db.commit()
            print(f"Updated user_id {user.user_id}: {', '.join(changes)}.")
            return 0

        if args.promote_existing or args.reactivate:
            print(f"No account exists for {email}, but --promote-existing/--reactivate was given.")
            print(
                "Check the email. To create a NEW admin account, re-run without those flags. Nothing was changed."
            )
            return 1

        print(f"No account exists for {email}. A NEW platform admin account will be created.")
        password = os.environ.get("APEXRX_ADMIN_PASSWORD")
        if password is None:
            password = getpass_fn(f"Password (min {MIN_PASSWORD_LENGTH} chars): ")
            if getpass_fn("Repeat password: ") != password:
                print("Passwords do not match. Nothing was changed.", file=sys.stderr)
                return 1
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters. Nothing was changed.",
                file=sys.stderr,
            )
            return 1
        if not args.yes and not _confirm(f"Create platform admin {email} on {target.label}?", input_fn):
            print("Cancelled. Nothing was changed.")
            return 1
        user = User(
            name=args.name, email=email, password_hash=hash_password(password), is_platform_admin=True
        )
        db.add(user)
        db.commit()
        print(f"Created platform admin {email} (user_id {user.user_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
