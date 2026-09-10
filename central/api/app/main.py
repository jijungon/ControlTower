"""Control Tower 중앙 API (FastAPI).

Phase 0 엔드포인트(러너가 사용):
  GET  /api/servers            — 서버·게이트웨이 인벤토리
  POST /api/connection-tests   — 연결 테스트 결과 수신
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from .routers import connection_tests, servers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 개발용: 테이블 자동 생성. 운영은 Alembic 마이그레이션 권장(db/README.md).
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Control Tower API", version="0.0.1", lifespan=lifespan)
app.include_router(servers.router)
app.include_router(connection_tests.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
