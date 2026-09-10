"""API 테스트 픽스처 — in-memory 대신 임시 SQLite 파일 + TestClient."""
import os

# app 임포트 전에 테스트 DB로 고정 (임시 sqlite 파일, .gitignore 됨)
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ctower.db")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine
import app.models  # noqa: F401  테이블 등록


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
