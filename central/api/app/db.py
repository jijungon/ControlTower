"""DB 연결 — DATABASE_URL 로 Postgres(운영) 또는 SQLite(로컬) 선택."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 기본은 로컬 SQLite. compose 에서는 postgresql+psycopg://... 주입.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./controltower.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
