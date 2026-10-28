"""금고(IdP) 접속 기록 요약 파일 읽기 — IdP 서버가 1분마다 최근 14일치를 다시 쓰고, 수집기가 읽어 중앙에 올린다.

지금(1단계)은 '누가 · 언제 · 어느 환경 · 어떤 계정' 인증서(도장)를 받았나(금고 기록)까지. 어느 gw · 서버로 갔는지는 모른다.

규칙: '못 봤다' 를 '아무도 안 들어왔다' 로 적지 않는다.
- 파일 없음 · 권한 없음 · 머리 줄이 깨짐 → read_ok=False + 이유(화면에서 '못 봄')
- 이벤트 줄이 깨졌으면 그 줄만 빼고 몇 줄인지 센다(bad_lines) — 조용히 버리지 않는다
- 정상/못 봄/멈춤 판정은 중앙이 지금 시각으로 한다

파일 모양(IdP 쪽이 정함, IdP 4ade0a7 — 칸 이름이 바뀌면 _header() · _event() 두 곳만 고친다):
  첫 줄(머리): {"written_at", "host", "interval_seconds", "window_days", "source": "openbao-audit",
               "read_ok", "why", "files_read", "bad_lines", "events", "truncated", "lines_read"?}
               read_ok · why = IdP 가 금고 기록을 읽었나 → 여기선 audit_ok · audit_reason 으로 이름을 바꿔 올린다
               bad_lines · events = IdP 쪽 숫자 → source_bad_lines · header_events (우리 bad_lines 와 헷갈리지 않게)
  나머지 줄(최신순): {"at"(나노초까지), "kind": "person"|"machine"|"other", "who"(없을 수 있음), "env",
               "account"(개인 gw 계정이면 없음), "role", "serial"(10-28 오전 전 기록은 없음), "result", "reason"}
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

MAX_BYTES = 10_000_000  # IdP 가 5000건까지만 넘김 — 한 줄 수백 바이트면 몇 MB. 이보다 크면 이상한 파일
MAX_EVENTS = 20_000     # 그 이상은 잘라 올림(truncated)
KINDS = ("person", "machine", "other")
_FRAC = re.compile(r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$")


def _fail(why: str) -> dict[str, Any]:
    return {"read_ok": False, "read_error": why, "events": [], "bad_lines": 0}


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _str(v: Any) -> str | None:
    return None if v is None else str(v)


def _at(v: Any) -> str | None:
    """시각 — 금고는 나노초(소수 9자리)까지 적는데 파이썬은 6자리까지만 읽는다 → 마이크로초로 잘라 둔다. 못 읽으면 None."""
    if not isinstance(v, str) or not v:
        return None
    m = _FRAC.match(v.strip())
    if not m:
        return None
    norm = m.group(1) + (m.group(2)[:7] if m.group(2) else "") + m.group(3)
    try:
        datetime.fromisoformat(norm.replace("Z", "+00:00"))
    except ValueError:
        return None
    return norm


def _header(d: Any) -> dict[str, Any] | None:
    """첫 줄 → 머리. written_at 과 read_ok(참/거짓)가 없으면 머리로 안 본다."""
    if not isinstance(d, dict) or "written_at" not in d or not isinstance(d.get("read_ok"), bool):
        return None
    return {
        "written_at": _at(d["written_at"]) or str(d["written_at"]),  # 못 읽는 모양이면 그대로 — 중앙이 '기록 시각 모름'
        "host": _str(d.get("host")),
        "interval_seconds": _int(d.get("interval_seconds")) or None,
        "window_days": _int(d.get("window_days")),
        "audit_ok": d["read_ok"],
        "audit_reason": _str(d.get("why")),
        "files_read": _int(d.get("files_read")),       # 0 이면 중앙이 '못 봄'
        "lines_read": _int(d.get("lines_read")),       # 있으면 — 0 이면 '못 봄'
        "source_bad_lines": _int(d.get("bad_lines")),  # IdP 가 금고 기록에서 못 읽은 줄
        "header_events": _int(d.get("events")),        # IdP 가 적었다는 건수 — 받은 줄과 다르면 화면에 알림
        "truncated": d.get("truncated") is True,       # IdP 가 최근 몇천 건까지만 넘김
    }


def _event(d: Any) -> dict[str, Any] | None:
    """이벤트 한 줄 → 올릴 모양. 시각 · 환경 · 결과가 없거나 시각을 못 읽으면 깨진 줄로 본다(who 는 없을 수 있음)."""
    if not isinstance(d, dict) or not d.get("env") or not d.get("result"):
        return None
    at = _at(d.get("at"))
    if at is None:
        return None
    kind = d.get("kind")
    return {
        "at": at,
        "kind": kind if kind in KINDS else "other",
        "who": _str(d.get("who")) or None,
        "env": str(d["env"]),
        "account": _str(d.get("account")),
        "role": _str(d.get("role")),
        "serial": _str(d.get("serial")),
        "result": str(d["result"]),
        "reason": _str(d.get("reason")),
    }


def read_access(path: str) -> dict[str, Any]:
    """요약 파일 하나 → 중앙에 올릴 모양. 예외를 밖으로 던지지 않는다(수집기 루프가 멈추지 않게)."""
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
    events: list[dict[str, Any]] = []
    bad = 0
    for ln in lines[1:]:
        try:
            ev = _event(json.loads(ln))
        except json.JSONDecodeError:
            ev = None
        if ev is None:
            bad += 1
        elif len(events) < MAX_EVENTS:
            events.append(ev)
    cut = len(lines) - 1 - bad > len(events)
    return {
        "read_ok": True,
        "read_error": None,
        **head,
        "truncated": head["truncated"] or cut,
        "events": events,
        "bad_lines": bad,  # 우리가 깨져서 뺀 줄
        "event_lines": len(lines) - 1,  # 받은 이벤트 줄(깨진 것 포함) — 머리의 events 와 견줌
        "digest": hashlib.sha256(raw).hexdigest(),  # 내용이 바뀌었을 때만 올리려고
    }


def summary(snap: dict[str, Any]) -> str:
    """수집기 로그 한 줄 — 상태가 바뀔 때만 찍는다."""
    if not snap.get("read_ok"):
        return f"못 봄({snap.get('read_error')})"
    if not snap.get("audit_ok"):
        return f"못 봄(IdP 가 금고 기록을 못 읽음 — {snap.get('audit_reason') or '이유 모름'})"
    bad = f" · 깨진 줄 {snap['bad_lines']}" if snap.get("bad_lines") else ""
    return f"{len(snap['events'])}건{bad}"
