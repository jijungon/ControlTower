#!/bin/sh
# Control Tower 러너 주기 수집 — cron 용. 키가 있는 로컬(러너)에서 실행한다.
# 접속 점검 → 업데이트 → 버전 → 설정(conf) 을 접속된 서버만(--online) 수집해 중앙에 올린다.
#
# CT_CENTRAL_URL / CT_API_TOKEN 은 env 파일에서 읽는다(토큰을 스크립트·레포에 넣지 않음):
#   기본 경로 ~/.controltower/runner.env  (CT_ENV_FILE 로 변경 가능)
#   예)  CT_CENTRAL_URL=http://<중앙-VM-IP>:8010
#        CT_API_TOKEN=<중앙과 동일한 토큰>
#
# crontab 예: */15 * * * * /path/to/ControlTower/scripts/collect.sh >> ~/.controltower/collect.log 2>&1

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${CT_ENV_FILE:-$HOME/.controltower/runner.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

if [ -z "$CT_CENTRAL_URL" ] || [ -z "$CT_API_TOKEN" ]; then
  echo "[collect] CT_CENTRAL_URL / CT_API_TOKEN 미설정 ($ENV_FILE 확인)"; exit 1
fi
export CT_CENTRAL_URL CT_API_TOKEN
export PYTHONPATH="$REPO"
PY="$REPO/.venv/bin/python"

echo "===== $(date '+%F %T') collect start ($CT_CENTRAL_URL) ====="
"$PY" -m runner.cli probe             || echo "[collect] probe 실패"
"$PY" -m runner.cli updates --online  || echo "[collect] updates 실패"
"$PY" -m runner.cli versions --online || echo "[collect] versions 실패"
"$PY" -m runner.cli conf --online     || echo "[collect] conf 실패"
echo "===== $(date '+%F %T') collect done ====="
