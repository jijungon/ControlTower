"""러너 인증(공유 토큰) + 사용자 로그인 어댑터(IdP-옵셔널).

러너: require_runner — 공유 토큰(CT_API_TOKEN) Bearer 검사 (변경 없음).

사용자 로그인은 CT_AUTH_MODE 로 갈아끼운다:
  none (기본) — 로그인 없음. 익명 principal, 화면 열림(기존 동작).
  oidc        — Authentik OIDC 토큰(Bearer JWT) 검증 → 이메일·그룹. 미검증이면 401.
                검증 키: CT_OIDC_JWKS_URL(운영) 또는 CT_OIDC_PUBLIC_KEY(PEM).
  proxy       — 앞단 Authentik(프록시)이 요청마다 붙이는 X-authentik-jwt 의 서명을 검사 → 그 안의 이메일·그룹.
                글자 헤더(X-authentik-email · -groups)는 믿지 않는다 — 흉내 낸 값은 서명이 안 맞는다.
                검사: RS256 만 · 만료(exp) 필수 · issuer 필수(CT_OIDC_ISSUER — 같은 키로 서명하는 다른 앱 토큰을 거름)
                      · audience 는 CT_OIDC_AUDIENCE 를 넣으면. 키는 oidc 와 같이 CT_OIDC_JWKS_URL(또는 PUBLIC_KEY).
                토큰이 없거나 검사에 떨어지면 익명(= 누군지 모름 → 서버 탭은 막힘). 401 로 막지는 않는다.
                GET /api/me 가 검사 결과(토큰이 왔나 · 통과했나 · 까닭 · 적힌 iss · aud · 클레임 이름)를 같이 보여 준다.

기본이 none 이라 IdP 없이도 그대로 동작. 플랫폼이 서면 CT_AUTH_MODE=oidc 로 스위치만.
"""
from __future__ import annotations

import functools
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


def current_user(
    authorization: str = Header(default=""),
    x_authentik_jwt: str = Header(default=""),
) -> Principal:
    """현재 사용자 의존성. none=익명(열림), oidc=검증된 사용자(실패 401), proxy=서명 맞는 프록시 토큰(아니면 익명)."""
    mode = auth_mode()
    if mode == "proxy":
        return _from_proxy(x_authentik_jwt.strip())
    if mode != "oidc":
        return ANON
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    claims = _verify_oidc(token)
    return Principal(authenticated=True, email=claims.get("email"), groups=_groups(claims))


def _groups(claims: dict) -> list[str]:
    g = claims.get("groups")
    return [x for x in g if isinstance(x, str)] if isinstance(g, list) else []


def _from_proxy(token: str) -> Principal:
    return proxy_check(token)[0]


def proxy_check(token: str) -> tuple[Principal, dict]:
    """X-authentik-jwt 검사 → (사용자, 확인 내용). 확인 내용은 /api/me 가 그대로 보여 준다 — 운영에서 한 번 열어
    토큰이 오는지 · 그룹 클레임 이름 · aud 를 본다. iss · aud · claims 는 토큰에 적힌 값(검사 전)이고, 토큰 자체는 안 보인다."""
    if not token:
        return ANON, {"token": False, "ok": False, "reason": "X-authentik-jwt 없음 — 앞단 Authentik 을 안 거쳤거나 붙이지 않음"}
    if not settings.ct_oidc_issuer:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "proxy 모드엔 CT_OIDC_ISSUER 가 필요(같은 키로 서명하는 다른 앱 토큰을 거름)",
        )
    seen = {"token": True, **_written(token)}
    try:
        claims = _verify_oidc(token, require=("exp", "iss"))
    except HTTPException as e:
        if e.status_code != status.HTTP_401_UNAUTHORIZED:
            raise  # 키 설정 오류는 숨기지 않는다
        return ANON, {**seen, "ok": False, "reason": e.detail}
    if not claims.get("email"):
        return ANON, {**seen, "ok": False, "reason": "토큰에 email 이 없음"}
    user = Principal(authenticated=True, email=claims["email"], groups=_groups(claims))
    return user, {**seen, "ok": True, "reason": None}


def _written(token: str) -> dict:
    import jwt

    try:
        head = jwt.get_unverified_header(token)
        body = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}
    return {"alg": head.get("alg"), "iss": body.get("iss"), "aud": body.get("aud"), "claims": sorted(body)}


@functools.lru_cache(maxsize=4)
def _jwks_client(url: str):
    """JWKS 는 한 번 받아 5분 기억(PyJWKClient 기본) — proxy 는 요청마다 검사하므로 매번 받지 않게."""
    import jwt

    return jwt.PyJWKClient(url, timeout=5)


def _signing_key(token: str):
    """검증 키: JWKS URL 우선, 없으면 정적 공개키(PEM). 둘 다 없으면 설정 오류(500)."""
    if settings.ct_oidc_jwks_url:
        return _jwks_client(settings.ct_oidc_jwks_url).get_signing_key_from_jwt(token).key
    if settings.ct_oidc_public_key:
        return settings.ct_oidc_public_key
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "oidc · proxy 모드엔 CT_OIDC_JWKS_URL 또는 CT_OIDC_PUBLIC_KEY 가 필요",
    )


def _verify_oidc(token: str, require: tuple[str, ...] = ()) -> dict:
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
                "require": list(require),
            },
        )
    except HTTPException:
        raise
    except Exception as e:  # PyJWTError · JWKS 조회 실패 등 → 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}") from e
