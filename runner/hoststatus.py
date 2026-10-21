"""서버가 스스로 적는 상태 파일(예: IdP 서버의 status.json) 읽기 — 적는 쪽이 1분마다 갱신, 수집기가 읽어 중앙에 올린다.

규칙: '못 봤다' 를 '정상' 으로 적지 않는다.
- 파일 없음 · 권한 없음 · JSON 깨짐 · 필수 칸 없음 · 칸 모양이 다름 → read_ok=False + 이유(화면에서 '모름')
- 읽었으면 내용을 그대로 올리고, 정상/경보/낡음 판정은 중앙이 한다(지금 시각 기준으로 '낡음' 을 봐야 해서)

파일 모양(적는 쪽이 정함):
  {"written_at": ISO 시각, "host": 서버 이름, "interval_seconds": 60, "ok": bool,
   "problems": [확인된 문제], "unread": [보려 했는데 못 본 것], "signals": {...}}
"""
from __future__ import annotations

import json
from typing import Any

MAX_BYTES = 1_000_000  # 상태 파일은 몇 KB — 이보다 크면 이상한 파일
REQUIRED = ("written_at", "ok", "problems", "unread")
DEFAULT_INTERVAL = 60  # 파일에 갱신 주기가 없으면 1분으로 봄


def _fail(why: str) -> dict[str, Any]:
    return {"read_ok": False, "read_error": why}


def read_status(path: str) -> dict[str, Any]:
    """상태 파일 하나 → 중앙에 올릴 모양. 예외를 밖으로 던지지 않는다(수집기 루프가 멈추지 않게)."""
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
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail("JSON 이 깨짐")
    if not isinstance(data, dict):
        return _fail("JSON 모양이 다름(객체가 아님)")
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        return _fail(f"필수 칸 없음: {', '.join(missing)}")
    if not isinstance(data["ok"], bool) or not isinstance(data["problems"], list) or not isinstance(data["unread"], list):
        return _fail("칸 모양이 다름(ok 는 참/거짓, problems · unread 는 목록)")
    interval = data.get("interval_seconds")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
        interval = DEFAULT_INTERVAL
    signals = data.get("signals")
    return {
        "read_ok": True,
        "read_error": None,
        "written_at": str(data["written_at"]),
        "host": str(data["host"]) if data.get("host") is not None else None,
        "interval_seconds": interval,
        "ok": data["ok"],
        "problems": [str(x) for x in data["problems"]],
        "unread": [str(x) for x in data["unread"]],
        "signals": signals if isinstance(signals, dict) else None,
    }


def summary(snap: dict[str, Any]) -> str:
    """수집기 로그 한 줄 — 상태가 바뀔 때만 찍는다."""
    if not snap.get("read_ok"):
        return f"모름({snap.get('read_error')})"
    if snap["ok"] and not snap["problems"] and not snap["unread"]:
        return "정상"
    return f"경보(문제 {len(snap['problems'])} · 못 본 것 {len(snap['unread'])})"
