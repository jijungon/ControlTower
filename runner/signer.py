"""SSH 도장(단명 인증서) 받기 — OpenBao(금고) HTTP API 로 (bao CLI 불필요 — 중앙 inventory_source 와 같은 방식).

금고 로그인 → `ssh-<환경>/sign/<환경>-collector` 에 공개키를 보내 도장을 받는다(15분, 최대 30분).
  신분: AppRole(수집기는 ct-collector). role_id · secret_id 는 **파일**에서 읽는다 — 비밀 값을 환경변수에 두지 않는다.
  ★ 두 파일은 시작할 때 한 번이 아니라 **로그인할 때마다 새로 읽는다.** 금고가 만료 10일 전에 secret_id 를
    새 것으로 바꾸고 옛 것을 지운다 — 값을 기억해 두면 교체 뒤 로그인이 깨진다.
  본문은 public_key 하나만. 꼬리표(principal)는 금고 기본값(<환경>-appuser)이라 안 보낸다.
  ★ critical_options 는 절대 보내지 않는다 — 도장에 박힌 명령을 바꾸려는 요청이라 거절되거나 서버가 안 받는 도장이 나온다.
  (예전 자리 ssh-client-signer/sign/<역할> 은 금고에서 없어졌다.)

환경변수:
  CT_BAO_ADDR              금고 주소 (api 의 목록 읽기와 같은 곳)            ← 없으면 꺼짐
  CT_BAO_ROLE_ID_FILE      role_id 파일 경로
  CT_BAO_SECRET_ID_FILE    secret_id 파일 경로 (0600)
  CT_BAO_TOKEN             (로컬 시험용) 이미 받은 토큰 — 있으면 로그인 생략. 운영에선 쓰지 않는다.
  TLS (CT_BAO_ADDR 가 https:// 일 때만 — http 면 아무 영향 없음. api 의 inventory_source 와 같은 방식):
  CT_BAO_CACERT            금고 서버 인증서를 발급한 CA 묶음(PEM). 사설 CA 면 필수, 비면 OS 기본 신뢰 저장소
  CT_BAO_CLIENT_CERT       클라이언트 인증서(PEM) — 금고 · LB 가 mTLS 를 요구할 때
  CT_BAO_CLIENT_KEY        클라이언트 개인키(PEM). 인증서에 키가 같이 들어 있으면 생략

CT_SSH_MODE=cert(러너가 ~/.ssh/config 별칭으로 붙을 때, runner/access.py)의 ensure_cert 만 더:
  CT_SSH_KEY               서명할 키(.pub 를 서명) [기본 ~/.ssh/id_ed25519]
  CT_BAO_SSH_ENV           어느 환경의 도장인가 [기본 dev]
  CT_SSH_CERT_REQUIRED     1/true → 서명 실패 시 key 로 조용히 폴백하지 않고 SignerError 로 중단(운영 필수)
수집기의 도장 길(runner/certpath.py)은 login · sign 을 직접 부르고, 키는 수집할 때마다 임시로 만들고 지운다.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENVS = ("dev", "stg", "prod")
CACHE_SECONDS = 10 * 60  # ensure_cert 의 도장 재사용 — 15분 도장이 수집 중에 끊기지 않게 그보다 짧게

# ensure_cert 의 (key_path, cert_path, 받은 시각). 한 수집 = 서명 한 번.
_cache: tuple[str, str, float] | None = None
# 이미 낸 경고(서버 수만큼 반복 출력 방지).
_warned: set[str] = set()


class SignerError(RuntimeError):
    """도장을 못 받았다 — 까닭(파일 · 로그인 · 서명)을 그대로 담는다. 비밀 값은 담지 않는다."""


def configured() -> bool:
    """금고 주소가 있는가(도장을 받을 수 있게 설정됐나)."""
    return bool(os.getenv("CT_BAO_ADDR"))


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _key_path() -> str:
    return os.path.expanduser(os.getenv("CT_SSH_KEY", "~/.ssh/id_ed25519"))


def reset_cache() -> None:
    """테스트·재실행용: 프로세스 캐시를 비운다."""
    global _cache
    _cache = None
    _warned.clear()


def _warn(msg: str) -> None:
    """같은 메시지는 한 번만 — ssh_access_opts 는 서버마다 불린다."""
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"[signer] {msg}", file=sys.stderr)


def _ssl_context() -> ssl.SSLContext | None:
    """https 일 때 쓸 SSL 컨텍스트(사설 CA + mTLS). http 면 None(기본 그대로)."""
    if not (os.getenv("CT_BAO_ADDR") or "").lower().startswith("https:"):
        return None
    ctx = ssl.create_default_context(cafile=os.getenv("CT_BAO_CACERT") or None)
    client_cert = os.getenv("CT_BAO_CLIENT_CERT")
    if client_cert:  # mTLS — 수집기가 자기 신분증을 제시
        ctx.load_cert_chain(client_cert, os.getenv("CT_BAO_CLIENT_KEY") or None)
    return ctx


def _post(path: str, token: str | None, payload: dict) -> dict:
    """금고 HTTP POST → 응답 JSON. 실패면 SignerError(HTTP 코드 · 금고가 적어 보낸 까닭)."""
    addr = (os.getenv("CT_BAO_ADDR") or "").rstrip("/")
    if not addr:
        raise SignerError("CT_BAO_ADDR 가 비었다 — 금고 주소")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    req = urllib.request.Request(f"{addr}/v1/{path}", data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        # 컨텍스트 생성도 try 안에 — CA · 키 파일 경로가 틀리면 여기서 터진다.
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            errs = json.loads(exc.read() or b"{}").get("errors") or []
        except Exception:  # noqa: BLE001 — 까닭을 못 읽어도 코드는 남는다
            errs = []
        why = (" — " + "; ".join(str(e) for e in errs))[:300] if errs else ""
        raise SignerError(f"금고 {path}: HTTP {exc.code}{why}") from exc
    except Exception as exc:  # noqa: BLE001 — 원인을 삼키지 않고 까닭으로 남긴다
        raise SignerError(f"금고 {path}: {type(exc).__name__}: {exc}") from exc


def _read_file(var: str, what: str) -> str:
    """환경변수 var 가 가리키는 파일을 지금 읽는다. 없음 · 빈 파일 · 권한 없음은 분명한 까닭으로(값은 안 담음)."""
    path = (os.getenv(var) or "").strip()
    if not path:
        old = var.removesuffix("_FILE")
        extra = f" ({old} 같은 값 환경변수는 더 이상 안 읽는다 — 파일 경로로)" if os.getenv(old) else ""
        raise SignerError(f"{var} 가 비었다 — {what} 파일 경로{extra}")
    try:
        text = Path(path).read_text().strip()
    except FileNotFoundError as exc:
        raise SignerError(f"{what} 파일이 없다: {path}") from exc
    except PermissionError as exc:
        raise SignerError(f"{what} 파일을 읽을 권한이 없다: {path} (소유자 · 0600 · 컨테이너 사용자 확인)") from exc
    except OSError as exc:
        raise SignerError(f"{what} 파일을 못 읽는다: {path} ({type(exc).__name__})") from exc
    if not text:
        raise SignerError(f"{what} 파일이 비었다: {path}")
    return text


def login() -> str:
    """금고 토큰. CT_BAO_TOKEN(로컬 시험)이 있으면 그것, 아니면 AppRole 로그인 — 비밀 파일을 **이때마다** 새로 읽는다."""
    token = os.getenv("CT_BAO_TOKEN")
    if token:
        return token
    role_id = _read_file("CT_BAO_ROLE_ID_FILE", "role_id")
    secret_id = _read_file("CT_BAO_SECRET_ID_FILE", "secret_id")
    auth = _post("auth/approle/login", None, {"role_id": role_id, "secret_id": secret_id}).get("auth") or {}
    if not auth.get("client_token"):
        raise SignerError("AppRole 로그인 답에 토큰이 없다 — secret_id 만료가 가장 흔하다")
    return auth["client_token"]


def sign(env: str, public_key: str, token: str | None = None) -> str:
    """대상 서버의 환경(env)으로 공개키에 도장 → 도장 글(signed_key). 본문은 public_key 하나만."""
    if env not in ENVS:
        raise SignerError(f"모르는 환경: {env!r} (dev · stg · prod 만)")
    body = _post(f"ssh-{env}/sign/{env}-collector", token or login(), {"public_key": public_key})
    signed = (body.get("data") or {}).get("signed_key")
    if not signed:
        raise SignerError(f"금고 ssh-{env}/sign/{env}-collector: 답에 도장(signed_key)이 없다")
    return signed


# ── CT_SSH_MODE=cert — 러너가 ~/.ssh/config 별칭으로 붙을 때(runner/access.py) ──


def _fail(reason: str) -> None:
    """cert 모드 실패 처리 — 강제 모드면 중단, 아니면 경고를 남기고 key 폴백(None)."""
    if _truthy("CT_SSH_CERT_REQUIRED"):
        raise SignerError(f"CT_SSH_CERT_REQUIRED=1 인데 인증서를 못 받았다: {reason}")
    _warn(f"{reason} → key 모드로 폴백")
    return None


def ensure_cert(alias: str) -> tuple[str, str] | None:
    """(key_path, cert_path). 미설정 · 실패면 None(→ 호출측이 key 폴백). 10분 안에는 받은 도장을 다시 쓴다.

    alias 는 쓰지 않는다 — 환경은 CT_BAO_SSH_ENV 하나.
    """
    global _cache
    if not configured():
        return _fail("CT_BAO_ADDR 미설정 — cert 모드를 쓸 수 없다")
    if _cache is not None and time.monotonic() - _cache[2] < CACHE_SECONDS:
        return _cache[0], _cache[1]
    key = _key_path()
    pub = key + ".pub"
    if not Path(pub).exists():
        return _fail(f"서명할 공개키가 없다: {pub}")
    try:
        signed = sign((os.getenv("CT_BAO_SSH_ENV") or "dev").strip(), Path(pub).read_text())
    except SignerError as exc:
        return _fail(f"도장을 못 받음 — {exc}")
    cert = key + "-cert.pub"
    Path(cert).write_text(signed)
    _cache = (key, cert, time.monotonic())
    return key, cert
