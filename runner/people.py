"""사람 이름표 파일 읽기 — IdP 서버가 5분마다 Authentik 의 server-admin · developer 사람 목록을 적고, 수집기가 읽어 중앙에 올린다.

쓰는 곳: 서버 탭(운영자 이름 · 개발자 이름) · 접속 기록 탭('누가' 칸 이메일 옆 이름). 키는 이메일(소문자).

규칙: '못 봤다' 를 '아무도 없다' 로 적지 않는다.
- 파일 없음 · 권한 없음 · 머리 줄이 깨짐 → read_ok=False + 이유(화면에서 '이름 모름')
- 사람 줄이 깨졌으면 그 줄만 빼고 몇 줄인지 센다(bad_lines) — 조용히 버리지 않는다
- 정상/모름/멈춤 판정은 중앙이 지금 시각으로 한다

파일 모양(IdP 쪽이 정함, IdP 1e2f581 · 49034c6 — 칸 이름이 바뀌면 _header() · _person() 두 곳만 고친다):
  첫 줄(머리): {"written_at", "host", "interval_seconds"(300), "source": "authentik", "read_ok", "why",
               "groups": {"server-admin": 3, "developer": 1} 또는 못 읽었으면 null, "people": 사람 줄 수}
               read_ok · why = IdP 가 Authentik 을 읽었나 → 여기선 list_ok · list_reason 으로 이름을 바꿔 올린다
               source → origin, people → header_people (올리는 이름 · 우리 people 목록과 헷갈리지 않게)
  나머지 줄(이메일 순, 이메일 없는 사람은 맨 뒤): {"email"(소문자 · 없으면 null), "username", "name"(없으면 null),
               "groups"(server-admin · developer 중 속한 것), "active"(false = 막힌 계정 — 줄은 남음)}
  두 그룹 어디에도 없는 사람은 파일에 없다. 비밀번호 · 마지막 로그인 · 내부 번호는 없다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_BYTES = 2_000_000  # 사람 몇십 명 — 한 줄 백여 바이트. 이보다 크면 이상한 파일
MAX_PEOPLE = 5_000     # 그 이상은 잘라 올림(truncated)


def _fail(why: str) -> dict[str, Any]:
    return {"read_ok": False, "read_error": why, "people": [], "bad_lines": 0}


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _text(v: Any) -> str | None:
    """빈 글자 · 공백만 → None."""
    return (v.strip() or None) if isinstance(v, str) else None


def _groups(v: Any) -> dict[str, int] | None:
    """{"server-admin": 3, …} — 못 읽었으면 IdP 가 null 을 준다(0 과 다름). 모양이 다르면 None(모름)."""
    if not isinstance(v, dict):
        return None
    out = {str(k): _int(n) for k, n in v.items()}
    return out if all(n is not None for n in out.values()) else None


def _header(d: Any) -> dict[str, Any] | None:
    """첫 줄 → 머리. written_at 과 read_ok(참/거짓)가 없으면 머리로 안 본다."""
    if not isinstance(d, dict) or "written_at" not in d or not isinstance(d.get("read_ok"), bool):
        return None
    return {
        "written_at": str(d["written_at"]),  # 못 읽는 모양이면 그대로 — 중앙이 '기록 시각 모름'
        "host": _text(d.get("host")),
        "interval_seconds": _int(d.get("interval_seconds")) or None,
        "origin": _text(d.get("source")),     # authentik
        "list_ok": d["read_ok"],
        "list_reason": _text(d.get("why")),
        "groups": _groups(d.get("groups")),
        "header_people": _int(d.get("people")),  # IdP 가 적었다는 사람 수 — 받은 줄과 다르면 화면에 알림
    }


def _person(d: Any) -> dict[str, Any] | None:
    """사람 한 줄 → 올릴 모양. active(참/거짓)가 없거나 이메일 · 아이디가 둘 다 없으면 깨진 줄로 본다."""
    if not isinstance(d, dict) or not isinstance(d.get("active"), bool):
        return None
    email, username = _text(d.get("email")), _text(d.get("username"))
    if email is None and username is None:
        return None
    groups = d.get("groups")
    return {
        "email": email.lower() if email else None,  # IdP 가 이미 소문자로 주지만 한 번 더 — 키라서
        "username": username,
        "name": _text(d.get("name")),
        "groups": [str(g) for g in groups if isinstance(g, str)] if isinstance(groups, list) else [],
        "active": d["active"],
    }


def read_people(path: str) -> dict[str, Any]:
    """이름표 파일 하나 → 중앙에 올릴 모양. 예외를 밖으로 던지지 않는다(수집기 루프가 멈추지 않게)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return _fail("파일 없음")
    except PermissionError:
        return _fail("권한 없음")
    except IsADirectoryError:
        return _fail("파일이 아니라 폴더")
    except OSError as e:
        return _fail(f"못 읽음({e.strerror or type(e).__name__})")
    if len(raw) > MAX_BYTES:
        return _fail("파일이 너무 큼")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return _fail("글자가 깨짐(UTF-8 아님)")
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return _fail("빈 파일")
    try:
        head = _header(json.loads(lines[0]))
    except json.JSONDecodeError:
        head = None
    if head is None:
        return _fail("첫 줄(머리)이 깨짐 — written_at · read_ok 필요")
    people: list[dict[str, Any]] = []
    bad = 0
    for ln in lines[1:]:
        try:
            p = _person(json.loads(ln))
        except json.JSONDecodeError:
            p = None
        if p is None:
            bad += 1
        elif len(people) < MAX_PEOPLE:
            people.append(p)
    return {
        "read_ok": True,
        "read_error": None,
        **head,
        "people": people,
        "bad_lines": bad,  # 우리가 깨져서 뺀 줄
        "person_lines": len(lines) - 1,  # 받은 사람 줄(깨진 것 포함) — 머리의 people 과 견줌
        "truncated": len(lines) - 1 - bad > len(people),
        "digest": hashlib.sha256(raw).hexdigest(),  # 내용이 바뀌었을 때만 올리려고
    }


def summary(snap: dict[str, Any]) -> str:
    """수집기 로그 한 줄 — 상태가 바뀔 때만 찍는다."""
    if not snap.get("read_ok"):
        return f"이름 모름({snap.get('read_error')})"
    if not snap.get("list_ok"):
        return f"이름 모름(IdP 가 Authentik 을 못 읽음 — {snap.get('list_reason') or '이유 모름'})"
    bad = f" · 깨진 줄 {snap['bad_lines']}" if snap.get("bad_lines") else ""
    return f"{len(snap['people'])}명{bad}"
