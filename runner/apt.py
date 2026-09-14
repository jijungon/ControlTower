"""`apt list --upgradable` 출력 파서 (읽기 전용).

예시 줄:
  openssl/jammy-updates,jammy-security 3.0.13 amd64 [upgradable from: 3.0.2]
→ {name: openssl, from: 3.0.2, to: 3.0.13, security: True}  (suite 에 -security 포함)
"""
from __future__ import annotations

import re

_LINE = re.compile(
    r"^(?P<name>[^/\s]+)/(?P<suites>\S+)\s+"
    r"(?P<to>\S+)\s+\S+\s+"
    r"\[upgradable from:\s*(?P<from>[^\]]+)\]"
)


def parse_upgradable(text: str) -> list[dict]:
    """apt 출력 → [{name, from, to, security}]. 파싱 불가/헤더 줄은 건너뛴다."""
    pkgs: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Listing"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        pkgs.append(
            {
                "name": m.group("name"),
                "from": m.group("from").strip(),
                "to": m.group("to"),
                "security": "-security" in m.group("suites"),
            }
        )
    return pkgs
