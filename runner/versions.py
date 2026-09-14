"""툴체인 버전 프로브 + 파서 (읽기 전용).

각 서버에서 아래 명령을 실행해 버전 문자열을 파싱한다. 조회만 — 서버를 변경하지 않는다.
버전은 stdout/stderr 어느 쪽이든 나올 수 있어(예: java -version 은 stderr) 합쳐서 파싱한다.
"""
from __future__ import annotations

import re

# tool → 원격 실행 명령
PROBES: dict[str, str] = {
    "node": "node --version",
    "npm": "npm --version",
    "java": "java -version",
    "python": "python3 --version",
    "docker": "docker --version",
}

_VER = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def parse_version(tool: str, raw: str) -> str | None:
    """명령 출력에서 버전(x.y[.z])을 추출. 실패 시 None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if tool == "java":
        # openjdk version "17.0.9" 2023-10-17  → 따옴표 안 우선(날짜 오인 방지)
        q = re.search(r'version "([^"]+)"', raw)
        if q:
            m = _VER.search(q.group(1))
            if m:
                return m.group(1)
    m = _VER.search(raw)
    return m.group(1) if m else None
