"""러너 인증 — 공유 토큰(CT_API_TOKEN) Bearer 검사.

단일 머신 Phase 0 용 단순 공유 토큰. 다중 러너·토큰 해시(runners 테이블)는 추후.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import settings


def require_runner(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != settings.ct_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid runner token")
