"""
Minimal shared-secret protection for clinician/admin endpoints.

When ADMIN_API_KEY is configured, requests must send it in the
`X-Admin-Key` header. When it is not configured (local demo), the
endpoints are open and a warning is logged once at startup.
"""

import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_admin_key(x_admin_key: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().ADMIN_API_KEY
    if not expected:
        return
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Admin-Key header.")
