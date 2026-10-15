# Control Tower — 로컬 개발 (Docker 없이 SQLite 로 dev/test)
# venv 파이썬을 항상 명시해 pyenv 전역과의 PATH 충돌을 피한다.
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup dev web import runner conf collect agent migrate test lint clean

help:
	@echo "make setup   - venv + 의존성 + .env (최초 1회)"
	@echo "make dev     - 중앙 API 로컬 실행 (SQLite, :8000)"
	@echo "make web     - 프론트 로컬 실행 (Vite, :5173)"
	@echo "make import  - ~/.ssh/config 를 인벤토리에 임포트 (읽기 전용)"
	@echo "make runner  - 등록 서버 SSH 연결 테스트 → 상태 갱신"
	@echo "make migrate - DB 스키마를 최신으로(Alembic upgrade head)"
	@echo "make conf    - 관리 경로 conf 수집 → 드리프트 비교"
	@echo "make collect - 모든 수집기 1회 실행(import→test→conf→updates→versions[→gitlab])"
	@echo "make agent   - 화면 [다시 수집] 요청을 기다렸다 처리(GitLab 만, 켜 둔 동안)"
	@echo "make test    - 전체 테스트 (pytest)"
	@echo "make lint    - 코드 린트 (ruff)"
	@echo "make clean   - 캐시·로컬 DB 정리"

setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements-dev.txt -r central/api/requirements.txt -r runner/requirements.txt
	[ -f .env ] || cp .env.example .env
	@echo "완료. 'make dev' 또는 'make test'."

migrate:
	cd central/api && PYTHONPATH=. ../../$(VENV)/bin/alembic upgrade head

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

conf:
	$(PY) -m runner.cli conf

# 모든 수집기 1회. 주기 실행은 cron 에 등록: */5 * * * * cd <repo> && .venv/bin/python -m runner.cli all
# 또는 상주 실행: .venv/bin/python -m runner.cli all --loop --interval 300
collect:
	$(PY) -m runner.cli all

# 화면 [다시 수집] 버튼 → 이 수집기가 요청을 가져가 GitLab 을 다시 읽음. 서버에선 docker compose 의 collector 가 같은 일.
# 키가 있는 PC 에서 서버 compose 까지 읽으려면: $(PY) -m runner.cli agent --ssh
agent:
	$(PY) -m runner.cli agent

lint:
	$(VENV)/bin/ruff check .

clean:
	rm -rf .pytest_cache **/__pycache__ *.db central/api/*.db
