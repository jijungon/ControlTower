# Control Tower — 로컬 개발 (Docker 없이 SQLite 로 dev/test)
# venv 파이썬을 항상 명시해 pyenv 전역과의 PATH 충돌을 피한다.
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup dev web import runner test lint clean

help:
	@echo "make setup   - venv + 의존성 + .env (최초 1회)"
	@echo "make dev     - 중앙 API 로컬 실행 (SQLite, :8000)"
	@echo "make web     - 프론트 로컬 실행 (Vite, :5173)"
	@echo "make import  - ~/.ssh/config 를 인벤토리에 임포트 (읽기 전용)"
	@echo "make runner  - 등록 서버 SSH 연결 테스트 → 상태 갱신"
	@echo "make test    - 전체 테스트 (pytest)"
	@echo "make lint    - 코드 린트 (ruff)"
	@echo "make clean   - 캐시·로컬 DB 정리"

setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements-dev.txt -r central/api/requirements.txt -r runner/requirements.txt
	[ -f .env ] || cp .env.example .env
	@echo "완료. 'make dev' 또는 'make test'."

dev:
	cd central/api && ../../$(VENV)/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

web:
	cd central/web && npm install && npm run dev

test:
	$(PY) -m pytest -q

import:
	$(PY) -m runner.cli import

runner:
	$(PY) -m runner.cli test

lint:
	$(VENV)/bin/ruff check .

clean:
	rm -rf .pytest_cache **/__pycache__ *.db central/api/*.db
