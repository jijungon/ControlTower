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

    def upload_host_status(self, source: str, reader: str, snap: dict[str, Any]) -> dict[str, Any]:
        """서버가 스스로 적는 상태 파일을 읽은 결과(read_status) — 못 읽었으면 그 이유를 그대로 올린다."""
        r = self._client.post("/api/host-status", json={**snap, "source": source, "reader": reader})
        r.raise_for_status()
        return r.json()

    def upload_people(self, source: str, reader: str, snap: dict[str, Any]) -> dict[str, Any]:
        """사람 이름표 파일을 읽은 결과(read_people) — 못 읽었으면 그 이유를 그대로 올린다."""
        body = {k: v for k, v in snap.items() if k != "digest"}  # 지문은 '바뀌었나' 판단용, 중앙엔 안 보냄
        # source · reader 를 맨 뒤에 — 읽은 내용에 같은 이름이 있어도 덮어쓰지 않게(#72 와 같은 까닭)
        r = self._client.post("/api/idp-people", json={**body, "source": source, "reader": reader})
        r.raise_for_status()
        return r.json()

    def upload_access_log(self, source: str, reader: str, snap: dict[str, Any]) -> dict[str, Any]:
        """금고 접속 기록 요약 파일을 읽은 결과(read_access) — 못 읽었으면 그 이유를 그대로 올린다."""
        body = {k: v for k, v in snap.items() if k != "digest"}  # 지문은 '바뀌었나' 판단용, 중앙엔 안 보냄
        # source · reader 를 맨 뒤에 — 읽은 내용에 같은 이름이 있어도 덮어쓰지 않게(10-28 운영: 파일의 source 가
        # 'idp' 를 덮어 중앙이 늘 '연결 전' 으로 보였다)
        r = self._client.post("/api/access-log", json={**body, "source": source, "reader": reader})
        r.raise_for_status()
        return r.json()

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

    def upload_shapes(self, shapes: list[dict[str, Any]], replace: bool = False) -> dict[str, Any]:
        r = self._client.post("/api/cicd/shape", json={"shapes": shapes, "replace": replace})
        r.raise_for_status()
        return r.json()

    def upload_config(self, items: list[dict[str, Any]], replace: bool = False) -> dict[str, Any]:
        r = self._client.post("/api/cicd/config", json={"items": items, "replace": replace})
        r.raise_for_status()
        return r.json()

    def list_shapes(self) -> list[dict[str, Any]]:
        """지난 수집의 비교표 — GitLab 만 다시 읽을 때 서버 compose 값을 이어 쓰려고."""
        r = self._client.get("/api/cicd/shape")
        r.raise_for_status()
        return r.json()

    def list_config(self) -> list[dict[str, Any]]:
        r = self._client.get("/api/cicd/config")
        r.raise_for_status()
        return r.json()

    # ── 다시 수집(화면 버튼) ──
    def claim_collect(self, kind: str, collector: str, mode: str, schedule: str | None = None) -> dict[str, Any] | None:
        """켜져 있다는 표시(+ 자동 수집 시각) + 기다리는 요청이 있으면 하나 가져옴(없으면 None)."""
        r = self._client.post("/api/collect/claim", json={"kind": kind, "collector": collector, "mode": mode, "schedule": schedule})
        r.raise_for_status()
        return r.json().get("request")

    def request_auto(self, kind: str, since: str) -> dict[str, Any]:
        """매일 정해 둔 시각이 지났을 때 — since 뒤로 끝난 수집이 없으면 중앙이 자동 요청을 만듦."""
        r = self._client.post("/api/collect/auto", json={"kind": kind, "since": since})
        r.raise_for_status()
        return r.json()

    def finish_collect(self, request_id: int, ok: bool, message: str | None) -> None:
        r = self._client.post(f"/api/collect/requests/{request_id}/finish", json={"ok": ok, "message": message})
        r.raise_for_status()

    def close(self) -> None:
        self._client.close()
