from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_JWT_SECRET = os.getenv("JWT_SECRET", "dhan-algo-trading-secret-change-me")
_ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
_ADMIN_PASS_HASH = hashlib.sha256(
    os.getenv("ADMIN_PASSWORD", "admin123").encode()
).hexdigest()

_TOKEN_EXPIRY = 86400  # 24h

security = HTTPBearer(auto_error=False)


def _sign(payload: str) -> str:
    return hmac.new(_JWT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_token(username: str) -> str:
    exp = int(time.time()) + _TOKEN_EXPIRY
    payload = f"{username}:{exp}"
    sig = _sign(payload)
    return f"{payload}:{sig}"


def verify_token(token: str) -> Optional[str]:
    parts = token.split(":")
    if len(parts) != 3:
        return None
    username, exp_str, sig = parts
    try:
        exp = int(exp_str)
    except ValueError:
        return None
    if time.time() > exp:
        return None
    expected_sig = _sign(f"{username}:{exp_str}")
    if not hmac.compare_digest(sig, expected_sig):
        return None
    return username


def authenticate(username: str, password: str) -> Optional[str]:
    pass_hash = hashlib.sha256(password.encode()).hexdigest()
    if username == _ADMIN_USER and hmac.compare_digest(pass_hash, _ADMIN_PASS_HASH):
        return create_token(username)
    return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = verify_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user
