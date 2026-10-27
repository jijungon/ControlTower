"""중앙 API 설정 — 환경변수 + `.env` 파일에서 주입 (pydantic-settings).

우선순위: 실제 환경변수(컨테이너·compose가 주입) > `.env` 파일 > 기본값.
따라서 운영(compose)에서는 environment 로 주입되고, 로컬 개발에서는 루트 `.env` 를 읽는다.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from .secret_source import hydrate_from_vault


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

    # gw · 서버 목록 — 금고에서 읽기만 (서버 탭 '누가 · 어디로'). off=안 읽음(기본), vault=AppRole 로 읽음
    ct_inventory_mode: str = "off"                      # CT_INVENTORY_MODE
    ct_inventory_addr: str = ""                         # CT_INVENTORY_ADDR (비면 CT_VAULT_ADDR)
    ct_inventory_mount: str = "inventory"               # CT_INVENTORY_MOUNT
    ct_inventory_role_id: str = ""                      # CT_INVENTORY_ROLE_ID (비밀 아님 — 누구인가)
    ct_inventory_secret_id_file: str = ""               # CT_INVENTORY_SECRET_ID_FILE (비밀 — 0600 파일)
    ct_inventory_cache_seconds: int = 60                # CT_INVENTORY_CACHE_SECONDS

    # 서버 상태 파일이 '낡음' 인 기준 — 파일의 갱신 주기(interval_seconds)의 몇 배가 지나도록 안 바뀌면 경보
    ct_host_status_stale_factor: float = 5.0           # CT_HOST_STATUS_STALE_FACTOR


# vault 모드면 OpenBao KV → env 주입(Settings 읽기 전). env 모드(기본)면 no-op.
hydrate_from_vault()
settings = Settings()
