"""중앙 API 클라이언트 (동기). 러너 토큰으로 인증."""
from __future__ import annotations

from typing import Any

import httpx


class CentralAPI:
    def __init__(self, base_url: str, token: str):
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )

    def list_servers(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/servers")
        r.raise_for_status()
        return r.json()

    def import_servers(self, servers: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/servers/import", json={"servers": servers})
        r.raise_for_status()
        return r.json()

    def post_connection_tests(self, results: list[dict[str, Any]]) -> None:
        r = self._client.post("/api/connection-tests", json={"results": results})
        r.raise_for_status()

    def close(self) -> None:
        self._client.close()
