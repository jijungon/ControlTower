"""GitLab CI 조회 (읽기 전용) — 프로젝트의 최근 파이프라인 상태.

토큰은 러너 로컬에만 둔다(PRIVATE-TOKEN 헤더). 중앙엔 결과 상태만 올리고 토큰은 저장하지 않는다.
transport 인자는 테스트에서 httpx.MockTransport 주입용.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


def fetch_latest_pipeline(
    base_url: str,
    token: str,
    project: str,
    timeout: int = 8,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any] | None:
    """프로젝트의 최근 파이프라인 1건. 없거나 오류면 None.

    project: 숫자 id 또는 'group/repo' 경로(경로는 URL 인코딩).
    반환: {status, ref, sha, web_url}
    """
    pid = quote(str(project), safe="")
    url = f"{base_url.rstrip('/')}/api/v4/projects/{pid}/pipelines"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as c:
            r = c.get(
                url,
                params={"per_page": 1, "order_by": "updated_at", "sort": "desc"},
                headers={"PRIVATE-TOKEN": token},
            )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None
    p = arr[0]
    return {
        "status": p.get("status"),
        "ref": p.get("ref"),
        "sha": p.get("sha"),
        "web_url": p.get("web_url"),
    }


def fetch_repo_file(
    base_url: str,
    token: str,
    project: str,
    path: str,
    ref: str = "main",
    timeout: int = 8,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    """repo 파일 원문을 읽는다(raw). 없거나 오류면 None. 선언본 버전 파싱용(읽기 전용)."""
    pid = quote(str(project), safe="")
    fpath = quote(path, safe="")
    url = f"{base_url.rstrip('/')}/api/v4/projects/{pid}/repository/files/{fpath}/raw"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as c:
            r = c.get(url, params={"ref": ref}, headers={"PRIVATE-TOKEN": token})
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    return r.text


def fetch_repo_tree(
    base_url: str,
    token: str,
    project: str,
    ref: str = "main",
    timeout: int = 8,
    *,
    transport: httpx.BaseTransport | None = None,
    max_pages: int = 50,
) -> list[str] | None:
    """repo 의 파일 경로 전체(재귀, blob 만). 오류면 None. config repo 폴더 훑기용(읽기 전용)."""
    pid = quote(str(project), safe="")
    url = f"{base_url.rstrip('/')}/api/v4/projects/{pid}/repository/tree"
    paths: list[str] = []
    page = "1"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as c:
            for _ in range(max_pages):
                r = c.get(
                    url,
                    params={"ref": ref, "recursive": "true", "per_page": 100, "page": page},
                    headers={"PRIVATE-TOKEN": token},
                )
                if r.status_code != 200:
                    return None
                paths += [i["path"] for i in r.json() if i.get("type") == "blob" and i.get("path")]
                page = r.headers.get("X-Next-Page", "")
                if not page:
                    break
    except httpx.HTTPError:
        return None
    return paths
