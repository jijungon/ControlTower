"""`yum/dnf check-update` 출력 파서 (읽기 전용).

check-update 는 현재 버전은 안 보여주고 '올릴 대상 버전'만 준다 → from 은 비움.
보안 분류는 updateinfo 플러그인이 필요해 기본은 일반으로 둔다(apt 만큼 정확치 않음).
예시 줄:  bind.x86_64   32:9.11.4-26.P2.el7_9.16   updates
"""
from __future__ import annotations

import re

# 헤더/잡음 줄(패키지 아님)
_SKIP = ("obsoleting", "security:", "last metadata", "loaded plugins", "excluding", "no match")
_VER = re.compile(r"\d+[.:-]")  # 버전처럼 보이는지(숫자+구분자)


def parse_yum(text: str) -> list[dict]:
    """yum/dnf check-update → [{name, from, to, security}]. 헤더/빈 줄은 건너뜀."""
    pkgs: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if not line or any(low.startswith(s) for s in _SKIP):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        name_arch, version = parts[0], parts[1]
        if "." not in name_arch or not _VER.search(version):
            continue
        name = name_arch.rsplit(".", 1)[0]  # name.arch → name
        pkgs.append({"name": name, "from": "", "to": version, "security": False})
    return pkgs
