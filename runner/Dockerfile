# 수집기(runner agent) — ControlTower 서버에 같이 띄워 화면 [다시 수집] 요청을 처리한다.
# GitLab 만 읽는다(서버에 SSH 키 없음) — 서버 compose 칸은 지난 수집 값을 이어 쓴다.
# 빌드 컨텍스트 = runner/ → 컨테이너 안 /app/runner 패키지로 둔다(python -m runner.cli).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./runner/requirements.txt
RUN pip install --no-cache-dir -r runner/requirements.txt
COPY . ./runner

CMD ["python", "-m", "runner.cli", "agent"]
