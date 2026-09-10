# 개발 워크플로우 — worktree(기능 단위) + 테스트 + PR

## 0. 로컬 개발 (Docker 없이 — 주 개발 모드)

기본은 **SQLite** 라 Docker/Postgres 없이 바로 돈다. `Makefile` 로 감싼다(venv 명시 → pyenv PATH 충돌 회피).

```bash
make setup     # venv + 의존성 + .env 준비 (최초 1회)
make dev       # 중앙 API 로컬 실행 (SQLite, hot-reload) → http://127.0.0.1:8000/health
make test      # 전체 테스트
```

- 로컬 DB = `controltower.db`(SQLite, gitignore). Postgres 로 붙이고 싶으면 `docker compose up -d db` 후 `.env` 의 `DATABASE_URL` 만 교체.
- 전체 스택(db+api+web)을 컨테이너로 보려면 `docker compose up -d --build`. 평소 개발은 `make dev` 로 충분.


## 1. 브랜치 · worktree

**기능 하나 = 브랜치 하나 = worktree 하나.** `main` 은 항상 초록(테스트 통과).

```bash
# 기능 시작: main 에서 새 worktree + 브랜치
git worktree add ../ct-wt/server-inventory -b feat/server-inventory
cd ../ct-wt/server-inventory
#   ... 작업 · 커밋 ...

# 끝: 푸시 → PR, 머지 후 정리
git push -u origin feat/server-inventory
git worktree remove ../ct-wt/server-inventory
```

명명: `feat/<기능>` · `fix/<버그>` · `chore/<잡무>`.

기능 → 브랜치 매핑(예):

| 브랜치 | 범위 |
|---|---|
| `feat/central-api` | 중앙 API 기반 — 러너 인증(토큰)·서버 등록 |
| `feat/server-inventory` | 서버·접속키 인벤토리 + `~/.ssh/config` 임포트 (Phase 0) |
| `feat/build-versions` | 빌드 버전·설치 항목 (GitLab 연동) |
| `feat/conf` | conf 관리·드리프트·push |
| `feat/updates` | update 관리 |
| `feat/cicd` | CI/CD 배포 현황 (Phase 5) |
| `feat/web` | React 프론트 |

## 2. 테스트 (pytest)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -r central/api/requirements.txt
pip install -r runner/requirements.txt      # 러너 테스트도 돌릴 때
pytest                    # 전체 (central/api/tests + runner/tests)
pytest central/api/tests  # API 만
```

- **백엔드(FastAPI)**: `TestClient` + 임시 SQLite. 외부 의존·DB 컨테이너 불필요.
- **러너**: SSH·GitLab 은 목(mock). ssh-config 파서·키스토어는 단위 테스트.
- worktree 마다 자체 `.venv` 를 두면 브랜치 간 의존성 충돌이 없다.

## 3. PR 플로우

1. worktree 에서 작업 → 로컬 `pytest` 초록 확인
2. `git push -u origin feat/...`
3. **PR/MR 생성 → CI 가 `pytest` 실행(머지 게이트)** → 리뷰 → `main` 머지
4. `git worktree remove` 로 정리

> CI: GitHub Actions(`.github/workflows/ci.yml`)가 push(main)·모든 PR 에서 `pytest` 실행.

## 4. Phase 0 사용법 (러너 인벤토리)

**`~/.ssh/config` 는 읽기 전용**으로만 쓴다 — 이 도구는 절대 수정·역동기화하지 않는다.

```bash
make dev                              # 중앙 API (:8000)
python -m runner.cli import --dry-run # 미리보기(전송 안 함)
make import                           # ~/.ssh/config → 인벤토리
make runner                           # 등록 서버 SSH 연결 테스트 → 상태 갱신
make web                              # 프론트에서 서버·상태 확인 (:5173)
```

- `.env` 필수값: `CT_API_TOKEN`(러너↔중앙 공유). ssh config 가 기본 경로가 아니면 `CT_SSH_CONFIG`.
- 접속 테스트는 시스템 ssh 가 `~/.ssh/config`(ProxyJump·키)를 그대로 사용한다(별도 키스토어 불필요).
