#!/bin/sh
# 스키마를 Alembic 으로 맞춘 뒤 API 기동.
#  - 이미 alembic 추적 중  → upgrade head (새 마이그레이션 적용)
#  - 추적 없는데 기존 스키마 있음(도입 시점) → stamp head (현 상태를 head 로 표시, 데이터 보존)
#  - 완전 새 DB → upgrade head (전체 생성)
set -e

if alembic current 2>/dev/null | grep -q '[0-9a-f]'; then
  echo "[entrypoint] alembic 추적 중 → upgrade head"
  alembic upgrade head
elif python -c "import sqlalchemy as sa; from app.db import engine; raise SystemExit(0 if 'servers' in sa.inspect(engine).get_table_names() else 1)"; then
  echo "[entrypoint] 기존 스키마 감지(추적 없음) → stamp head (데이터 보존)"
  alembic stamp head
else
  echo "[entrypoint] 새 DB → upgrade head (전체 생성)"
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
