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

    def list_conf_targets(self) -> list[str]:
        r = self._client.get("/api/conf/targets")
        r.raise_for_status()
        return r.json()

    def upload_conf_snapshots(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/conf/snapshots", json={"snapshots": snapshots})
        r.raise_for_status()
        return r.json()

    def list_apply_intents(self, status: str | None = None) -> list[dict[str, Any]]:
        r = self._client.get("/api/conf/apply", params={"status": status} if status else None)
        r.raise_for_status()
        return r.json()

    def get_apply_content(self, intent_id: int) -> dict[str, Any]:
        r = self._client.get(f"/api/conf/apply/{intent_id}/content")
        r.raise_for_status()
        return r.json()

    def post_apply_result(
        self, intent_id: int, status: str, backup_path: str | None = None, error: str | None = None
    ) -> dict[str, Any]:
        r = self._client.post(
            f"/api/conf/apply/{intent_id}/result",
            json={"status": status, "backup_path": backup_path, "error": error},
        )
        r.raise_for_status()
        return r.json()

    def post_apply_rollback(self, intent_id: int) -> dict[str, Any]:
        r = self._client.post(f"/api/conf/apply/{intent_id}/rollback")
        r.raise_for_status()
        return r.json()

    def upload_update_snapshots(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/updates/snapshots", json={"snapshots": snapshots})
        r.raise_for_status()
        return r.json()

    def upload_tool_snapshots(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/versions/snapshots", json={"snapshots": snapshots})
        r.raise_for_status()
        return r.json()

    def list_version_repo_targets(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/versions/repo-targets")
        r.raise_for_status()
        return r.json()

    def upload_repo_snapshots(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/versions/repo-snapshots", json={"snapshots": snapshots})
        r.raise_for_status()
        return r.json()

    def list_cicd_targets(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/cicd/targets")
        r.raise_for_status()
        return r.json()

    def upload_cicd_status(self, statuses: list[dict[str, Any]]) -> dict[str, Any]:
        r = self._client.post("/api/cicd/status", json={"statuses": statuses})
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()
