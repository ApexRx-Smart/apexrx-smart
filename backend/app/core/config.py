from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

MIN_JWT_SECRET_LENGTH = 32
# Example/placeholder values that must never sign real tokens.
KNOWN_PLACEHOLDER_SECRETS = frozenset(
    {
        "replace-with-a-long-random-secret",
        "test-secret-key-that-is-long-enough",
        "secret",
        "changeme",
        "change-me",
    }
)
PLACEHOLDER_MARKERS = ("replace-with", "change-me", "changeme", "placeholder", "your-secret", "your_secret")


class Settings(BaseSettings):
    # "production" unless explicitly set: development-only behaviour (the mock
    # SMS provider, the /dev endpoints) is never enabled by accident.
    app_env: Literal["development", "test", "production"] = "production"

    database_url: str
    # Validated by _strong_jwt_secret: at least 32 characters, not a placeholder.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)

    # Comma-separated list in the environment, e.g.
    # CORS_ORIGINS=http://localhost:5501,http://127.0.0.1:5501
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://127.0.0.1:5501",
        "http://localhost:5501",
    ]

    # Organization verification documents.
    upload_dir: Path = BACKEND_DIR / "uploads"
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    allowed_document_mime_types: Annotated[list[str], NoDecode] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]

    # Where document files live. "auto" uses Supabase Storage when SUPABASE_URL
    # and SUPABASE_SECRET_KEY are set, and the local upload_dir otherwise
    # (local development and tests). Metadata always stays in PostgreSQL.
    document_storage: Literal["auto", "supabase", "local"] = "auto"
    supabase_url: str | None = None
    # Server-side only: never sent to the browser or written to logs.
    supabase_secret_key: SecretStr | None = None
    supabase_bucket_name: str = "organization-documents"
    supabase_timeout_seconds: int = Field(default=20, gt=0)

    # Login throttling (failed attempts in a moving window). The counters live in
    # RATE_LIMIT_STORAGE_URI: "memory://" (per process, reset on restart) or e.g.
    # "redis://host:6379" when running several instances.
    login_max_failures_per_account: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=20, ge=1)
    login_failure_window_seconds: int = Field(default=900, ge=1)
    # Lifetime of the "known browser" tokens that keep the owner able to sign
    # in while their account is locked by someone else's wrong passwords.
    device_token_max_age_days: int = Field(default=90, ge=1)
    rate_limit_storage_uri: str = "memory://"
    # Header holding the real client IP. Only set it to a header that the proxy
    # in front of the app is VERIFIED to overwrite on every request (see
    # tools/render-ip-check); otherwise clients can choose their own rate-limit
    # key. Never X-Forwarded-For. Unset (the safe default): the TCP peer is
    # used, and per-IP limiting is skipped when that peer is a private proxy.
    trusted_client_ip_header: str | None = None

    # Default currency for offers and purchase orders (ISO 4217).
    default_currency: str = "RWF"

    # Phone verification by SMS one-time code (see app/services/otp.py).
    # When true, creating a pharmacy requires the owner's phone to be verified.
    phone_verification_required: bool = True
    # SMS provider adapter name (app/services/sms). Unset: SMS is not
    # configured and sending a code fails with a clear 503. "mock" is refused
    # in production.
    sms_provider: str | None = None
    # Optional sender name/number passed to real providers.
    sms_sender_id: str | None = None
    otp_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    otp_max_attempts: int = Field(default=5, ge=1, le=20)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    otp_max_sends_per_phone_per_hour: int = Field(default=5, ge=1)
    otp_max_sends_per_user_per_hour: int = Field(default=10, ge=1)
    otp_max_sends_per_ip_per_hour: int = Field(default=20, ge=1)
    # Phone numbers: parsed with this default region, and only numbers from
    # these regions are accepted (ISO 3166 codes, comma-separated).
    phone_default_region: str = "RW"
    phone_allowed_regions: Annotated[list[str], NoDecode] = ["RW"]

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Never echo submitted values (e.g. the JWT secret) in validation errors.
        hide_input_in_errors=True,
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def _strong_jwt_secret(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("JWT_SECRET_KEY is empty. Set it to a long random value.")
        lowered = value.strip().lower()
        if lowered in KNOWN_PLACEHOLDER_SECRETS or any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            raise ValueError(
                "JWT_SECRET_KEY is a placeholder/example value. Generate a real one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if len(value) < MIN_JWT_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_LENGTH} characters long.")
        return value

    @field_validator("phone_allowed_regions")
    @classmethod
    def _upper_regions(cls, value: list[str]) -> list[str]:
        regions = [r.strip().upper() for r in value if r.strip()]
        if not regions:
            raise ValueError("PHONE_ALLOWED_REGIONS must list at least one region, e.g. RW.")
        return regions

    @field_validator("sms_provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("trusted_client_ip_header", mode="before")
    @classmethod
    def _blank_header_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, str) and value.strip().lower() == "x-forwarded-for":
            raise ValueError("TRUSTED_CLIENT_IP_HEADER must not be X-Forwarded-For (clients can forge it).")
        return value.strip() if isinstance(value, str) else value

    @field_validator("cors_origins", "allowed_document_mime_types", "phone_allowed_regions", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
