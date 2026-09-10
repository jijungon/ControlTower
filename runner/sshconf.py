"""~/.ssh/config 파서 — Host 별 접속 정보 추출 (와일드카드 Host 제외).

**읽기 전용**: 이 도구(러너·중앙)는 ~/.ssh/config 를 절대 수정하지 않는다.
임포트는 단방향(config → 중앙)이며, 중앙에서 서버를 편집해도 로컬 ssh config 로 역동기화하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class SSHHost:
    alias: str
    hostname: str | None = None
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    proxy_jump: str | None = None


def _split(line: str) -> tuple[str | None, str | None]:
    # "Key value" 또는 "Key=value"
    if "=" in line and " " not in line.split("=", 1)[0].strip():
        k, v = line.split("=", 1)
        return k.strip(), v.strip()
    parts = line.split(None, 1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


def parse_ssh_config(path: str) -> list[SSHHost]:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return []
    hosts: list[SSHHost] = []
    cur: SSHHost | None = None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:  # 읽기 전용(수정 안 함)
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, val = _split(line)
            if key is None or val is None:
                continue
            k = key.lower()
            if k == "host":
                aliases = [a for a in val.split() if "*" not in a and "?" not in a]
                cur = SSHHost(alias=aliases[0]) if aliases else None
                if cur is not None:
                    hosts.append(cur)
            elif cur is not None:
                if k == "hostname":
                    cur.hostname = val
                elif k == "user":
                    cur.user = val
                elif k == "port":
                    try:
                        cur.port = int(val)
                    except ValueError:
                        pass
                elif k == "identityfile":
                    cur.identity_file = val
                elif k == "proxyjump":
                    cur.proxy_jump = val
    return hosts
