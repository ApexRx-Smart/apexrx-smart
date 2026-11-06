# Plan: security hardening (audit findings 2-5)

Branch: `feature/security-hardening`, from `main` (45c741c).

1. **seed_demo guard** (`app/scripts/safety.py`). The target comes from the engine the script writes through.
   - Allowed by default: a loopback host whose database name is not production-like.
   - Anything else needs `--allow-remote-database` plus retyping the exact host. Checked before any write.
2. **Login throttling** with `limits` 5.8.0, using a moving window held in process memory.
   - 5 failures per account and 20 per IP, in 15 minutes.
   - Checked before the password is verified. Returns 429 with Retry-After.
   - The account key is a hashed email, so it gives no account enumeration.
   - The client IP comes only from `TRUSTED_CLIENT_IP_HEADER` (Render: True-Client-IP). X-Forwarded-For is refused.
   - A non-public peer without the header skips the IP limit, so there is no global lockout.
3. **create_admin**
   - Shows the account if it already exists.
   - `--promote-existing` and `--reactivate` are separate, explicit flags, and both are refused for a missing account.
   - Never changes a password.
   - Non-local targets need the host retyped, even with `--yes`.
4. **JWT secret** must be at least 32 characters. Placeholders are rejected, and inputs are hidden in errors.
   - The `.env.example` placeholder is rejected on purpose.
   - Tests use a random secret.
5. **Tests**: config, rate limits, scripts and privilege-escalation regressions; the full suite; ruff; Playwright admin e2e plus a 429 UI check.

No production access, no deploy, no merge.
