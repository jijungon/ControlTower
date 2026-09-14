"""GitLab repo 선언본 버전 파서 (읽기 전용, 순수 함수).

지원 소스:
  - .nvmrc            → node
  - package.json      → node(engines.node), nest(@nestjs/core)
  - pom.xml           → java(java.version / maven.compiler.source|release)
extract_versions(files) 는 파일 내용 dict 를 받아 {tool: version} 를 만든다(순수 → 테스트 용이).
"""
from __future__ import annotations

import json
import re

_VER = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_MAJOR = re.compile(r"(\d+)")


def _ver_or_major(spec: str | None) -> str | None:
    """'^10.3.0'→10.3.0, '>=20'→20, '20.x'→20, 'v18.19.1'→18.19.1."""
    if not spec:
        return None
    m = _VER.search(spec)
    if m:
        return m.group(1)
    m = _MAJOR.search(spec)
    return m.group(1) if m else None


def parse_nvmrc(text: str) -> str | None:
    return _ver_or_major(text.strip()) if text else None


def parse_package_json(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return out
    node = (data.get("engines") or {}).get("node")
    v = _ver_or_major(node)
    if v:
        out["node"] = v
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    v = _ver_or_major(deps.get("@nestjs/core"))
    if v:
        out["nest"] = v
    return out


def parse_pom_java(text: str) -> str | None:
    for tag in ("java.version", "maven.compiler.release", "maven.compiler.source"):
        m = re.search(rf"<{re.escape(tag)}>\s*([^<]+?)\s*</{re.escape(tag)}>", text)
        if m:
            return _ver_or_major(m.group(1))
    return None


def extract_versions(files: dict[str, str | None]) -> dict[str, str]:
    """files: {'.nvmrc':..., 'package.json':..., 'pom.xml':...}(없으면 None) → {tool: version}."""
    out: dict[str, str] = {}
    pkg = files.get("package.json")
    if pkg:
        out.update(parse_package_json(pkg))
    nvmrc = files.get(".nvmrc")
    if nvmrc:
        v = parse_nvmrc(nvmrc)
        if v:
            out["node"] = v  # .nvmrc 가 package.json engines 보다 우선
    pom = files.get("pom.xml")
    if pom:
        j = parse_pom_java(pom)
        if j:
            out["java"] = j
    return out
