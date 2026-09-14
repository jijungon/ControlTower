FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000
# 기동 전 Alembic 으로 스키마 정합(도입/신규/업그레이드 자동 판별) 후 uvicorn
CMD ["./entrypoint.sh"]
