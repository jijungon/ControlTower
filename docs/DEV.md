# 개발 워크플로우 — worktree(기능 단위) + 테스트 + PR

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

> CI 설정 파일(`.github/workflows/ci.yml` 또는 `.gitlab-ci.yml`)은 원격 플랫폼(GitHub/GitLab) 확정 후 추가.
