"""Application configuration loaded from environment / .env file."""

import os
from dotenv import load_dotenv

load_dotenv()


def _require_secret_key() -> str:
    val = os.environ.get("SECRET_KEY", "")
    if not val or val == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is not set or is the insecure default. "
            "Generate one with: uv run python manage_users.py secret"
        )
    return val


class Config:
    SECRET_KEY = _require_secret_key()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    _ssl_active = os.path.exists(
        os.environ.get("SSL_CERT", "certs/cert.pem")
    ) and os.path.exists(os.environ.get("SSL_KEY", "certs/key.pem"))
    SESSION_COOKIE_SECURE = os.environ.get(
        "COOKIE_SECURE", "auto"
    ).lower() == "true" or (
        os.environ.get("COOKIE_SECURE", "auto").lower() == "auto" and _ssl_active
    )
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
    SESSION_ABSOLUTE_LIFETIME = int(
        os.environ.get("SESSION_ABSOLUTE_LIFETIME", str(10 * 3600))
    )  # 10 h
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(4 * 1024 * 1024)))
