# Plan: real SMS OTP phone verification

Branch: `feature/sms-otp-verification`, from `main` (25c1f0a, includes #21).

## Findings
- The demo code 472916 is checked only in the browser (`pharmacies.js`), and the copy says email.
- There is no backend OTP code.
- The phone is collected at the profile step, after the verify step.

## Plan
1. **Migration**
   - New `phone_verification` table: user, E.164 phone, purpose, HMAC code hash, expiry, attempts, consumed and invalidated timestamps.
   - `app_user.verified_phone` and `phone_verified_at`, kept separate from the editable `phone`.
2. **SMS sending**, `app/services/sms/`
   - A provider interface, a mock provider, and a registry chosen by `SMS_PROVIDER`.
   - Production refuses the mock (503). Delivery failure gives 502. There is no fallback to the mock.
3. **OTP logic**, `app/services/otp.py`
   - `secrets` six-digit code, 5-minute expiry, single use.
   - HMAC bound to user, phone and purpose; a new code invalidates older ones.
   - At most 5 attempts, a 60-second cooldown, and send limits per phone, per user and per trustworthy IP.
4. **Endpoints** (login required)
   - `GET /auth/phone/status`, `POST /auth/phone/send-code`, `POST /auth/phone/verify`.
   - Development only: `GET /dev/sms/latest`, which returns the caller's own latest code. It is not mounted in production and is checked on each request.
5. **Server-side enforcement**: a pharmacy's create, or a change to its phone, needs the caller's verified phone, and that becomes the organization phone.
6. **Modes**
   - `APP_ENV` defaults to production; development opts in.
   - On Render, a non-production `APP_ENV` refuses to start.
   - `PHONE_VERIFICATION_REQUIRED` allows a provider-less rollout.
7. **Frontend**: same verify step with phone, send, code, resend countdown, loading and errors. 472916 is removed.
8. **Tests and docs**; PR for review only. No deploy, no provider accounts.
