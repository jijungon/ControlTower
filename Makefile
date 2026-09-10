# Control Tower — 로컬 개발 (Docker 없이 SQLite 로 dev/test)
# venv 파이썬을 항상 명시해 pyenv 전역과의 PATH 충돌을 피한다.
VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: help setup dev test runner clean

help:
	@echo "make setup   - venv 생성 + 의존성 설치 + .env 준비"
	@echo "make dev     - 중앙 API 로컬 실행 (SQLite, hot-reload, :8000)"
	@echo "make test    - 전체 테스트 (pytest)"
	@echo "make runner  - 러너 연결 테스트 (로컬 .env + 키스토어 필요)"
	@echo "make clean   - 캐시·로컬 DB 정리"

setup:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements-dev.txt -r central/api/requirements.txt -r runner/requirements.txt
	[ -f .env ] || cp .env.example .env
	@echo "완료. 'make dev' 또는 'make test'."

dev:
	cd central/api && ../../$(VENV)/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	$(PY) -m pytest -q

runner:
	$(PY) -m runner.cli test

clean:
	rm -rf .pytest_cache **/__pycache__ *.db central/api/*.db
