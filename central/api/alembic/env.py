"""Alembic 환경 — app 모델(Base.metadata)과 DATABASE_URL(env) 사용.

alembic 은 central/api 에서 실행한다(로컬: cd central/api / 도커: /app).
DB URL 은 코드 config 와 동일하게 환경변수 DATABASE_URL 로 받는다.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine

import app.models  # noqa: F401  — 모든 모델을 Base.metadata 에 등록
from app.db import Base

# 앱과 동일하게 저장소 루트 .env 도 반영(도커에선 컨테이너 env 가 우선).
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./controltower.db")


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,  # SQLite ALTER 지원(배치 모드)
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
