# Control Tower — Phase 0 스캐폴딩

서버 중앙 관리 서비스의 **Phase 0(기반)** 뼈대. 전체 기획은 `docs/ControlTower-PLAN.md` 참고.

## 원칙 (코드에 반영됨)

- **중앙 무키**: 중앙 VM(사내망)은 SSH 키를 저장하지 않는다. DB엔 자격증명 *별칭*만.
- **러너 로컬 키**: 키가 있는 local에서 러너가 실행. 자동 수집은 PC가 켜진 동안만.
- **nested ssh**: gw에 로컬 gw키로 접속 → gw 위에서 gw가 가진 키로 대상에 접속.
- **gw별 동시성 제한**: 15개 gw·대규모 서버 대비 세마포어로 상한.

## 구성

```
ControlTower/
├── docker-compose.yml       # 중앙 서비스: db + api + web
├── .env.example
├── central/
│   ├── api/                 # FastAPI 백엔드 (Dockerfile, requirements, app/)
│   │   └── app/            main.py · db.py · models.py · routers/{servers,connection_tests}.py
│   └── web/                 # React 프론트 (지금은 placeholder + nginx)
├── db/
│   ├── schema.sql           # 데이터 모델 정본 (Phase 0)
│   └── README.md
└── runner/                  # 러너 CLI (로컬 네이티브 — compose 밖, 로컬 키 접근)
    └── cli.py · ssh.py · api.py · keystore.py · config.py · requirements.txt
```

## 중앙 서비스 실행 (Docker)

```bash
cp .env.example .env          # 값 채우기 (DB_PASSWORD, CT_SECRET)
docker compose up -d --build
# api  http://127.0.0.1:8000/health   ·   web  http://127.0.0.1:8080
```

중앙(db + api + web)은 사내 VM에서 컨테이너로 실행. 러너는 로컬에서 따로(아래).

## 데이터 모델 (db/schema.sql)

`servers`(gw도 role=gateway로 등록) · `server_groups` · `tags`/`server_tags` ·
`credential_refs`(별칭만, 비밀 없음) · `runners` · `connection_tests` ·
`users`(admin/operator/viewer) · `audit_logs`(append-only).

접속 경로 = `servers.access_method`(direct|via_gateway) + `gateway_id` 체인.

## 러너 실행 (Phase 0)

```bash
cd ControlTower
python -m venv .venv && source .venv/bin/activate
pip install -r runner/requirements.txt

cp runner/keystore.example.toml ~/.controltower/keystore.toml   # 키 경로 채우기
export CT_CENTRAL_URL="http://<중앙VM>:8000"
export CT_API_TOKEN="<러너 토큰>"

python -m runner.cli test     # 전 서버 SSH 연결 테스트 → 결과 중앙 업로드
```

## 남은 일 (내일 이어서)

- [ ] 중앙 FastAPI 앱: `GET /api/servers`, `POST /api/connection-tests` (schema.sql 기반)
- [ ] 러너 인증(API 토큰) 실제 연결, `runners.last_seen_at` 갱신
- [ ] `known_hosts=None` 제거 → 호스트키 검증 도입
- [ ] 서버 인벤토리 등록 UI/CLI (그룹·태그·gateway 지정)
- [ ] (Phase 1) `collect` 서브커맨드 — 빌드 버전·conf 수집기(YAML). 접속키는 `~/.ssh/config` 임포트

## 미확정 (열린 질문 5번)

빌드 환경 위치가 정해지면(`docs/ControlTower-빌드환경-체크리스트.md`) 버전 수집을
SSH(설치형) 또는 GitLab API(컨테이너형)로 붙인다. Phase 0 뼈대엔 영향 없음.
