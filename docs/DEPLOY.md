# 배포 — 중앙(사내 VM) + 러너(로컬)

구조: **러너(로컬 PC, 키 보유)** 가 게이트웨이를 넘어 서버에 접속·수집·적용하고, 결과만 **HTTPS/HTTP 로 중앙(사내 VM)** 에 올린다. 중앙은 SSH 키를 갖지 않는다.

```
로컬 PC(러너) ──ssh(로컬 키)──▶ GW ──▶ 대상 서버
     │  HTTP(S)  (결과↑ / 기준본↓)
사내 VM(중앙: db·api·web, 키 0)
```

## 1. VM 요구사항
- 리눅스(Ubuntu 22.04 등) · **Docker + docker compose v2** · git
- 사내망에서 **러너가 VM 에 접근 가능**(포트 열림). public IP 불필요.
- 2 vCPU / 4GB / 20GB+ 면 충분.

## 2. 중앙 올리기 (VM 에서)
```bash
git clone https://github.com/jijungon/ControlTower.git
cd ControlTower
cp .env.example .env
```
`.env` 에서 최소 이것들 채우기:
```
DB_PASSWORD=<강한 비밀번호>
CT_SECRET=<랜덤 문자열>
CT_API_TOKEN=<러너와 공유할 진짜 비밀>   # 쓰기 인증. dev 기본값 금지!
BIND_ADDR=0.0.0.0                        # 사내망의 러너가 접근하도록 개방 (로그인 없이 둘 때만)
```
> ⚠ **로그인(IdP·리버스 프록시) 뒤에 세울 때는 `BIND_ADDR` 를 넣지 말 것**(기본 127.0.0.1). 0.0.0.0 으로 열면 사내망에서 8090·8000 에 바로 닿아 로그인을 건너뛴다. 프록시는 포트가 아니라 **같은 docker 망**으로 web 에 붙인다 — 서버의 `docker-compose.override.yml`(커밋 안 됨)에 `web` 을 프록시의 external 망에 붙이는 설정. 이 파일이 없어지면 로그인은 되는데 화면이 502.
기동(버전 · 커밋을 같이 넣으면 화면 맨 위에 보인다 — 안 넣으면 '버전 모름(dev)'):
```bash
CT_BUILD=$(git rev-parse --short HEAD) \
CT_VERSION=$(git describe --tags --exact-match 2>/dev/null || echo dev) \
docker compose up -d --build
```
- api 컨테이너 진입점이 **Alembic 으로 스키마 정합**(신규 생성 / 기존 stamp / 업그레이드 자동 판별) 후 기동 → **재배포해도 데이터 보존**.
- 확인: `curl -s http://localhost:8000/health` → `{"status":"ok", "build":"<커밋>"}`, 웹은 `http://<VM-IP>:8090` — 맨 위 오른쪽에 `<커밋> · 월/일 시:분 반영`.
- 버전 표시: 화면 맨 위가 `v0.0.68 · 이슈 #59 · <커밋> · 10/28 10:15 반영` (이슈가 없으면 이슈 칸만 빠짐).
  - `CT_VERSION` = 버전 태그. PR 이 main 에 합쳐지면 GitHub 작업(`.github/workflows/version-tag.yml`)이 그 커밋에 `v0.0.{PR번호}` 를 달고, PR 이 닫은 이슈가 있으면 `+{이슈}`(여럿이면 `+59.60`)를 붙인다. 이슈는 PR 본문에 `Closes #59` 로 적은 것만 잡힌다.
  - `--exact-match` — 지금 커밋에 태그가 있을 때만 버전을 보인다(없으면 dev → 커밋만). 옛 태그를 끌어다 쓰지 않는다. 태그는 `git pull` 이 같이 받아 온다(안 보이면 `git fetch --tags`).
  - `CT_BUILD` = 커밋. 둘 다 반영할 때마다 넣는다(`.env` 에 고정해 두면 다음 반영 때 옛 값이 보이니 명령 앞에 붙이는 쪽). 안 넣으면 지어내지 않고 '버전 모름(dev)'.

## 3. 러너 연결 (로컬 PC 에서)
로컬 `.env`(또는 환경변수):
```
CT_CENTRAL_URL=http://<VM-사내IP>:8000     # 예: http://10.0.0.10:8000
CT_API_TOKEN=<중앙과 동일한 값>
```
수집 실행(읽기 전용):
```bash
python -m runner.cli import
python -m runner.cli probe --online         # 접속 점검 + 2FA
python -m runner.cli updates --online
python -m runner.cli versions --online
# 주기 실행은 cron: */15 * * * * cd <repo> && .venv/bin/python -m runner.cli all
```
→ 결과가 VM 중앙에 쌓이고, `http://<VM-IP>:8090` 화면에 뜬다.

## 4. 운영 보안 체크
- `CT_API_TOKEN` **진짜 비밀**(러너·중앙 공유). 읽기는 공개, 쓰기(업로드·적용 결과)는 이 토큰.
- 가능하면 **HTTPS**: web(nginx) 앞에 사내 리버스 프록시/인증서. 그러면 `CT_CENTRAL_URL=https://...`.
- 방화벽: VM 의 8000/8090 을 **러너가 있는 대역에서만** 허용. 로그인 뒤에 세웠으면 8000/8090 은 아예 열지 않음(위 ⚠).
- `.env`·키는 커밋 금지(.gitignore 됨). 키는 러너 로컬에만.

## 5. 업그레이드 / 스키마 변경
```bash
cd ControlTower && git pull --tags \
  && CT_BUILD=$(git rev-parse --short HEAD) CT_VERSION=$(git describe --tags --exact-match 2>/dev/null || echo dev) \
     docker compose up -d --build
```
- 스키마가 바뀌었어도(마이그레이션 포함) **데이터 유지**. `down -v` 불필요.
