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
BIND_ADDR=0.0.0.0                        # 사내망의 러너가 접근하도록 개방
```
기동:
```bash
docker compose up -d --build
```
- api 컨테이너 진입점이 **Alembic 으로 스키마 정합**(신규 생성 / 기존 stamp / 업그레이드 자동 판별) 후 기동 → **재배포해도 데이터 보존**.
- 확인: `curl -s http://localhost:8000/health` → `{"status":"ok"}`, 웹은 `http://<VM-IP>:8090`.

## 3. 러너 연결 (로컬 PC 에서)
로컬 `.env`(또는 환경변수):
```
CT_CENTRAL_URL=http://<VM-사내IP>:8000     # 예: http://20.20.6.210:8000
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
- 방화벽: VM 의 8000/8090 을 **러너가 있는 대역에서만** 허용.
- `.env`·키는 커밋 금지(.gitignore 됨). 키는 러너 로컬에만.

## 5. 업그레이드 / 스키마 변경
```bash
cd ControlTower && git pull && docker compose up -d --build
```
- 스키마가 바뀌었어도(마이그레이션 포함) **데이터 유지**. `down -v` 불필요.
