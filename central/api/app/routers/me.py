"""GET /api/me — 현재 로그인 사용자(로그인 어댑터). none 모드면 익명(authenticated=false)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import Principal, current_user

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: Principal = Depends(current_user)) -> dict:
    return {"authenticated": user.authenticated, "email": user.email, "groups": user.groups}
