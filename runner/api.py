"""중앙 API 클라이언트 — 서버 인벤토리 수신, 결과 업로드.

Phase 0 에서 쓰는 엔드포인트(중앙 FastAPI 가 제공해야 함):
  GET  /api/servers            -> 서버·게이트웨이 인벤토리 목록
  POST /api/connection-tests   -> {"results": [...]} 연결 테스트 결과 저장
"""
from __future__ import annotations

from typing import Any

import httpx


class CentralAPI:
    def __init__(self, base_url: str, token: str):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    async def list_servers(self) -> list[dict[str, Any]]:
        r = await self._client.get("/api/servers")
        r.raise_for_status()
        return r.json()

    async def post_connection_tests(self, results: list[dict[str, Any]]) -> None:
        r = await self._client.post("/api/connection-tests", json={"results": results})
        r.raise_for_status()

    # TODO(Phase 1): fetch_collection_jobs(), post_snapshots()

    async def aclose(self) -> None:
        await self._client.aclose()
