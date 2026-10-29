"""금고(OpenBao) 로그인 · 도장 받기 (#58) — 금고 없이 urlopen 을 가짜로.

지키는 것:
  - role_id · secret_id 는 **파일**에서, 로그인할 때마다 새로 읽는다(금고가 secret_id 를 바꿔도 다음 로그인이 산다)
  - 파일이 없음 · 빈 파일 · 권한 없음 → 분명한 까닭(값은 안 담음), 금고에 아무것도 안 보냄
  - 도장 자리는 ssh-<환경>/sign/<환경>-collector, 본문은 public_key 하나만 — critical_options 는 절대 안 보냄
"""
import io
import json
import os
import urllib.error

import pytest

from runner import signer


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def bao(monkeypatch, tmp_path):
    """금고 대역 — 받은 요청(경로 · 본문)을 기록. 파일 비밀 두 개를 tmp 에 만든다."""
    monkeypatch.setenv("CT_BAO_ADDR", "http://bao.example:8200")
    for v in ("CT_BAO_TOKEN", "CT_BAO_ROLE_ID", "CT_BAO_SECRET_ID"):
        monkeypatch.delenv(v, raising=False)
    role, secret = tmp_path / "role_id", tmp_path / "secret_id"
    role.write_text("role-A\n")
    secret.write_text("secret-1\n")
    monkeypatch.setenv("CT_BAO_ROLE_ID_FILE", str(role))
    monkeypatch.setenv("CT_BAO_SECRET_ID_FILE", str(secret))
    seen: list[dict] = []

    def fake_urlopen(req, timeout=10, context=None):
        path = req.full_url.split("/v1/", 1)[1]
        seen.append({"path": path, "body": json.loads(req.data.decode()), "token": req.get_header("X-vault-token")})
        if path == "auth/approle/login":
            return FakeResp({"auth": {"client_token": f"tok-{len(seen)}"}})
        return FakeResp({"data": {"signed_key": f"CERT for {path}"}})

    monkeypatch.setattr(signer.urllib.request, "urlopen", fake_urlopen)
    return {"seen": seen, "role": role, "secret": secret}


def test_로그인마다_비밀_파일을_새로_읽는다(bao):
    """★ 사용자 결정(10-29): 금고가 만료 10일 전에 secret_id 를 바꾼다 — 기억해 둔 값으로 로그인하면 깨진다."""
    assert signer.login() == "tok-1"
    bao["secret"].write_text("secret-2\n")  # 금고가 새 비밀로 바꿈(옛 것은 지워짐)
    bao["role"].write_text("role-B\n")
    assert signer.login() == "tok-2"
    bodies = [s["body"] for s in bao["seen"]]
    assert len(bodies) == 2 and all(s["path"] == "auth/approle/login" for s in bao["seen"])  # 실제로 두 번 보냈나 먼저
    assert bodies[0] == {"role_id": "role-A", "secret_id": "secret-1"}
    assert bodies[1] == {"role_id": "role-B", "secret_id": "secret-2"}


@pytest.mark.parametrize("env", ["dev", "stg", "prod"])
def test_도장_자리와_본문(bao, env):
    assert signer.sign(env, "ssh-ed25519 AAAA ct-collector\n") == f"CERT for ssh-{env}/sign/{env}-collector"
    login, sign = bao["seen"]
    assert login["path"] == "auth/approle/login"
    assert sign["path"] == f"ssh-{env}/sign/{env}-collector"
    assert sign["token"] == "tok-1"
    assert sign["body"] == {"public_key": "ssh-ed25519 AAAA ct-collector\n"}  # public_key 하나만
    assert "critical_options" not in json.dumps(sign["body"]) and "valid_principals" not in sign["body"]


def test_받은_토큰이_있으면_로그인을_다시_안_한다(bao):
    signer.sign("dev", "ssh-ed25519 AAAA k", token="tok-given")
    assert [s["path"] for s in bao["seen"]] == ["ssh-dev/sign/dev-collector"]
    assert bao["seen"][0]["token"] == "tok-given"


def test_모르는_환경이면_금고에_안_보낸다(bao):
    with pytest.raises(signer.SignerError, match="모르는 환경"):
        signer.sign("qa", "ssh-ed25519 AAAA k")
    assert bao["seen"] == []


def test_비밀_파일_경로가_비면_분명한_까닭(bao, monkeypatch):
    monkeypatch.delenv("CT_BAO_SECRET_ID_FILE")
    with pytest.raises(signer.SignerError, match="CT_BAO_SECRET_ID_FILE 가 비었다"):
        signer.login()
    # 예전처럼 값을 환경변수에 넣어 두었으면 — 더 이상 안 읽는다고 알려 줌(값은 안 담음)
    monkeypatch.setenv("CT_BAO_SECRET_ID", "plain-secret-value")
    with pytest.raises(signer.SignerError) as e:
        signer.login()
    assert "더 이상 안 읽는다" in str(e.value) and "plain-secret-value" not in str(e.value)
    assert bao["seen"] == []


def test_비밀_파일이_없으면(bao):
    bao["secret"].unlink()
    with pytest.raises(signer.SignerError, match="secret_id 파일이 없다"):
        signer.login()
    assert bao["seen"] == []


def test_비밀_파일이_비었으면(bao):
    bao["role"].write_text("\n")
    with pytest.raises(signer.SignerError, match="role_id 파일이 비었다"):
        signer.login()
    assert bao["seen"] == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root 는 권한 없는 파일도 읽는다")
def test_비밀_파일을_읽을_권한이_없으면(bao):
    bao["secret"].chmod(0)
    try:
        with pytest.raises(signer.SignerError) as e:
            signer.login()
    finally:
        bao["secret"].chmod(0o600)
    assert "권한이 없다" in str(e.value) and "secret-1" not in str(e.value)
    assert bao["seen"] == []


def test_금고가_거절하면_코드와_까닭(bao, monkeypatch):
    def deny(req, timeout=10, context=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"errors": ["invalid role or secret ID"]}'))

    monkeypatch.setattr(signer.urllib.request, "urlopen", deny)
    with pytest.raises(signer.SignerError, match="HTTP 400 — invalid role or secret ID"):
        signer.login()


def test_로그인_답에_토큰이_없으면(bao, monkeypatch):
    monkeypatch.setattr(signer.urllib.request, "urlopen", lambda req, timeout=10, context=None: FakeResp({"auth": None}))
    with pytest.raises(signer.SignerError, match="secret_id 만료"):
        signer.login()


def test_도장이_답에_없으면(bao, monkeypatch):
    monkeypatch.setenv("CT_BAO_TOKEN", "t")
    monkeypatch.setattr(signer.urllib.request, "urlopen", lambda req, timeout=10, context=None: FakeResp({"data": {}}))
    with pytest.raises(signer.SignerError, match="signed_key"):
        signer.sign("dev", "ssh-ed25519 AAAA k")
