"""중앙 API 설정 — 환경변수 + `.env` 파일에서 주입 (pydantic-settings).

우선순위: 실제 환경변수(컨테이너·compose가 주입) > `.env` 파일 > 기본값.
따라서 운영(compose)에서는 environment 로 주입되고, 로컬 개발에서는 루트 `.env` 를 읽는다.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./controltower.db"   # DATABASE_URL
    ct_secret: str = "dev-secret-change-me"              # CT_SECRET
    ct_api_token: str = "dev-runner-token"              # CT_API_TOKEN — 러너↔중앙 공유 토큰

    # 사용자 로그인 어댑터 (IdP-옵셔널). none=로그인 없음(기본), oidc=Authentik JWT 검증.
    ct_auth_mode: str = "none"                          # CT_AUTH_MODE
    ct_oidc_jwks_url: str = ""                          # CT_OIDC_JWKS_URL (운영: Authentik JWKS)
    ct_oidc_public_key: str = ""                        # CT_OIDC_PUBLIC_KEY (PEM; JWKS 대신 정적 키)
    ct_oidc_issuer: str = ""                            # CT_OIDC_ISSUER
    ct_oidc_audience: str = ""                          # CT_OIDC_AUDIENCE


settings = Settings()
