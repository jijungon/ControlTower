"""러너 인증(공유 토큰) + 사용자 로그인 어댑터(IdP-옵셔널).

러너: require_runner — 공유 토큰(CT_API_TOKEN) Bearer 검사 (변경 없음).

사용자 로그인은 CT_AUTH_MODE 로 갈아끼운다:
  none (기본) — 로그인 없음. 익명 principal, 화면 열림(기존 동작).
  oidc        — Authentik OIDC 토큰(Bearer JWT) 검증 → 이메일·그룹. 미검증이면 401.
                검증 키: CT_OIDC_JWKS_URL(운영) 또는 CT_OIDC_PUBLIC_KEY(PEM).

기본이 none 이라 IdP 없이도 그대로 동작. 플랫폼이 서면 CT_AUTH_MODE=oidc 로 스위치만.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Header, HTTPException, status

from .config import settings


def require_runner(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token != settings.ct_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid runner token")


@dataclass
class Principal:
    """요청을 보낸 사용자. none 모드에선 authenticated=False 익명."""

    authenticated: bool = False
    email: str | None = None
    groups: list[str] = field(default_factory=list)


ANON = Principal()


def auth_mode() -> str:
    return (settings.ct_auth_mode or "none").strip().lower() or "none"


def current_user(authorization: str = Header(default="")) -> Principal:
    """현재 사용자 의존성. none=익명(열림), oidc=검증된 사용자(실패 401)."""
    if auth_mode() != "oidc":
        return ANON
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    claims = _verify_oidc(token)
    return Principal(
        authenticated=True,
        email=claims.get("email"),
        groups=list(claims.get("groups") or []),
    )


def _signing_key(token: str):
    """검증 키: JWKS URL 우선, 없으면 정적 공개키(PEM). 둘 다 없으면 설정 오류(500)."""
    import jwt

    if settings.ct_oidc_jwks_url:
        return jwt.PyJWKClient(settings.ct_oidc_jwks_url).get_signing_key_from_jwt(token).key
    if settings.ct_oidc_public_key:
        return settings.ct_oidc_public_key
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "oidc 모드엔 CT_OIDC_JWKS_URL 또는 CT_OIDC_PUBLIC_KEY 가 필요",
    )


def _verify_oidc(token: str) -> dict:
    import jwt

    try:
        return jwt.decode(
            token,
            _signing_key(token),
            algorithms=["RS256"],
            audience=settings.ct_oidc_audience or None,
            issuer=settings.ct_oidc_issuer or None,
            options={
                "verify_aud": bool(settings.ct_oidc_audience),
                "verify_iss": bool(settings.ct_oidc_issuer),
            },
        )
    except HTTPException:
        raise
    except Exception as e:  # PyJWTError · JWKS 조회 실패 등 → 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
