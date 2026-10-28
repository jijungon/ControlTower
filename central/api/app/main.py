"""Control Tower 중앙 API (FastAPI).

Phase 0 엔드포인트(러너가 사용):
  GET  /api/servers            — 서버·게이트웨이 인벤토리
  POST /api/connection-tests   — 연결 테스트 결과 수신
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .auth import DEVELOPER_OPEN_API, auth_mode, developer_only, principal_of
from .db import Base, engine
from .routers import access, audit, cicd, collect, conf, connection_tests, host_status, me, servers, updates, versions

# 배포 확인은 이 값으로 한다(프론트 번들 grep 아님). 반영할 때 CT_VERSION/CT_BUILD 를 넣는다(compose 가 api 에 넘김).
# 아무도 안 넣으면 'dev' — 화면은 버전을 지어내지 않고 '버전 모름' 으로 보인다.
APP_VERSION = os.getenv("CT_VERSION", "dev")
APP_BUILD = os.getenv("CT_BUILD", "dev")
APP_STARTED = datetime.now(timezone.utc).isoformat(timespec="seconds")  # 이 API 가 뜬 시각 ≈ 반영 시각


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 안전망: 빈 DB(테스트·e2e·로컬 직접 기동)면 테이블 생성(멱등, 기존 테이블은 그대로).
    # 운영 스키마 '진화'(컬럼 추가 등)는 Alembic 이 담당한다(도커 진입점이 upgrade/stamp).
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Control Tower API", version=APP_VERSION, lifespan=lifespan)
app.include_router(servers.router)
app.include_router(connection_tests.router)
app.include_router(conf.router)
app.include_router(updates.router)
app.include_router(versions.router)
app.include_router(cicd.router)
app.include_router(collect.router)
app.include_router(host_status.router)
app.include_router(audit.router)
app.include_router(me.router)
app.include_router(access.router)


@app.middleware("http")
async def developer_server_tab_only(request: Request, call_next):
    """개발자(server-admin 아님)는 서버 탭이 쓰는 API 만 — 나머지는 읽기도 403(새로 생길 API 도 기본 막힘).
    그룹을 아는 모드(oidc · proxy)에서만. 신분증 오류는 각 API 가 지금처럼 다룬다(러너 공유 토큰도 여기로 빠짐)."""
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api/") and path not in DEVELOPER_OPEN_API and auth_mode() in ("oidc", "proxy"):
        try:
            user = await run_in_threadpool(
                principal_of, request.headers.get("authorization", ""), request.headers.get("x-authentik-jwt", "")
            )
        except HTTPException:
            user = None
        if user is not None and developer_only(user):
            return JSONResponse({"detail": "개발자는 서버 탭만 볼 수 있어요"}, status_code=403)
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    """상태 + 배포 버전. version=제품 버전(태그), build=빌드 식별자(커밋·런번호)."""
    return {"status": "ok", "version": APP_VERSION, "build": APP_BUILD}


@app.get("/api/version")
def version() -> dict:
    """화면 맨 위 버전 표시용 — /health 는 화면(nginx)이 /api 만 넘겨서 못 닿는다. started_at = 이 API 가 뜬 시각."""
    return {"version": APP_VERSION, "build": APP_BUILD, "started_at": APP_STARTED}
