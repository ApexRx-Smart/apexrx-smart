from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str = Field(min_length=16)
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

    # Default currency for offers and purchase orders (ISO 4217).
    default_currency: str = "RWF"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", "allowed_document_mime_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
