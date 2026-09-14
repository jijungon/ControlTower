"""Control Tower 중앙 API (FastAPI).

Phase 0 엔드포인트(러너가 사용):
  GET  /api/servers            — 서버·게이트웨이 인벤토리
  POST /api/connection-tests   — 연결 테스트 결과 수신
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from .routers import audit, cicd, conf, connection_tests, servers, updates, versions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 안전망: 빈 DB(테스트·e2e·로컬 직접 기동)면 테이블 생성(멱등, 기존 테이블은 그대로).
    # 운영 스키마 '진화'(컬럼 추가 등)는 Alembic 이 담당한다(도커 진입점이 upgrade/stamp).
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Control Tower API", version="0.0.1", lifespan=lifespan)
app.include_router(servers.router)
app.include_router(connection_tests.router)
app.include_router(conf.router)
app.include_router(updates.router)
app.include_router(versions.router)
app.include_router(cicd.router)
app.include_router(audit.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
