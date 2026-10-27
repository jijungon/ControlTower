"""GET /api/me — 현재 로그인 사용자(로그인 어댑터). none 모드면 익명(authenticated=false).

proxy 모드면 proxy 칸에 X-authentik-jwt 검사 결과도 — 켜기 전에 운영에서 한 번 열어 확인하는 길.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header

from ..auth import Principal, auth_mode, current_user, proxy_check

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: Principal = Depends(current_user), x_authentik_jwt: str = Header(default="")) -> dict:
    body = {"authenticated": user.authenticated, "email": user.email, "groups": user.groups}
    if auth_mode() == "proxy":
        body["proxy"] = proxy_check(x_authentik_jwt.strip())[1]
    return body
