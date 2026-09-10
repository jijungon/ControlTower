# db

- `schema.sql` — 참조 DDL (SQLite 기준). 데이터 모델의 정본.
- **개발**: API가 기동 시 SQLAlchemy 로 테이블 자동 생성(SQLite 또는 Postgres). 별도 init 불필요.
- **운영**: Alembic 마이그레이션 권장(추후 도입). Postgres 이관 시 `datetime('now')`→`now()`,
  `INTEGER PRIMARY KEY`→`GENERATED ... AS IDENTITY` 등 치환.
- compose 의 `db`(Postgres)는 빈 상태로 시작하고 API가 테이블을 만든다.
