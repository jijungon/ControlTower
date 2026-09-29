"""비밀 어댑터(secret_source) 테스트 — env(기본, no-op) + vault(가짜 KV, OpenBao 없이)."""
import json
import os

import pytest

from app import secret_source


def test_env_mode_is_default_and_noop(monkeypatch):
    monkeypatch.delenv("CT_SECRET_MODE", raising=False)
    assert secret_source.secret_mode() == "env"
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    secret_source.hydrate_from_vault()  # env 모드 → 아무것도 안 함
    assert os.getenv("CT_TESTSECRET_XYZ") is None


def test_vault_mode_unconfigured_is_noop(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.delenv("CT_VAULT_ADDR", raising=False)  # 미설정
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") is None


def test_vault_mode_injects_env(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "secret/data/controltower")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.delenv("CT_TESTSECRET_XYZ", raising=False)
    monkeypatch.setattr(
        secret_source, "_fetch_kv", lambda addr, path, token: {"CT_TESTSECRET_XYZ": "from-vault"}
    )
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") == "from-vault"


def test_vault_does_not_override_explicit_env(monkeypatch):
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "p")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.setenv("CT_TESTSECRET_XYZ", "explicit")  # 이미 설정됨
    monkeypatch.setattr(
        secret_source, "_fetch_kv", lambda addr, path, token: {"CT_TESTSECRET_XYZ": "from-vault"}
    )
    secret_source.hydrate_from_vault()
    assert os.getenv("CT_TESTSECRET_XYZ") == "explicit"  # setdefault → 안 덮음


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_kv_parses_v2(monkeypatch):
    """KV v2 응답(data.data) 파싱 — urlopen 을 가짜로."""
    payload = {"data": {"data": {"CT_API_TOKEN": "v2tok"}}}
    monkeypatch.setattr(
        secret_source.urllib.request,
        "urlopen",
        lambda req, timeout=5, context=None: FakeResp(payload),
    )
    got = secret_source._fetch_kv("https://bao.local", "secret/data/ct", "tkn")
    assert got == {"CT_API_TOKEN": "v2tok"}


# ── TLS (사설 CA + mTLS) ──


def test_http_addr_gets_no_ssl_context(monkeypatch):
    """http 면 컨텍스트 None — PoC/개발 경로는 전혀 안 바뀐다."""
    monkeypatch.setenv("CT_VAULT_CACERT", "/ignored.pem")
    assert secret_source._ssl_context("http://bao.local:8200") is None


def test_https_uses_private_ca_and_client_cert(monkeypatch, tmp_path):
    """https 면 사설 CA 를 신뢰하고, 클라이언트 인증서(mTLS)를 붙인다."""
    ca, crt, key = tmp_path / "ca.pem", tmp_path / "c.crt", tmp_path / "c.key"
    for p in (ca, crt, key):
        p.write_text("")
    loaded = {}
    monkeypatch.setenv("CT_VAULT_CACERT", str(ca))
    monkeypatch.setenv("CT_VAULT_CLIENT_CERT", str(crt))
    monkeypatch.setenv("CT_VAULT_CLIENT_KEY", str(key))
    monkeypatch.setattr(
        secret_source.ssl, "create_default_context", lambda cafile=None: _FakeCtx(loaded, cafile)
    )
    ctx = secret_source._ssl_context("https://bao.local:8200")
    assert ctx.cafile == str(ca)          # 사내 CA 를 신뢰
    assert loaded["chain"] == (str(crt), str(key))  # 내 신분증 제시


class _FakeCtx:
    def __init__(self, loaded, cafile):
        self.cafile, self._loaded = cafile, loaded

    def load_cert_chain(self, cert, key=None):
        self._loaded["chain"] = (cert, key)


def test_ssl_context_is_passed_to_urlopen(monkeypatch, tmp_path):
    """컨텍스트가 실제 요청에 전달되는지 — 이게 빠지면 mTLS 가 조용히 무시된다."""
    monkeypatch.delenv("CT_VAULT_CACERT", raising=False)  # OS 기본 신뢰 저장소로 충분
    monkeypatch.delenv("CT_VAULT_CLIENT_CERT", raising=False)
    seen = {}

    def fake_urlopen(req, timeout=5, context=None):
        seen["context"] = context
        return FakeResp({"data": {"data": {"K": "V"}}})

    monkeypatch.setattr(secret_source.urllib.request, "urlopen", fake_urlopen)
    secret_source._fetch_kv("https://bao.local", "secret/data/ct", "tkn")
    assert isinstance(seen["context"], secret_source.ssl.SSLContext)


# ── 조용한 폴백 방지 ──


def test_required_mode_raises_instead_of_dev_defaults(monkeypatch):
    """CT_SECRET_REQUIRED=1 이면 조회 실패 시 기동을 막는다(공개 기본값 서비스 방지)."""
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.setenv("CT_SECRET_REQUIRED", "1")
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "p")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.setattr(secret_source, "_fetch_kv", lambda *a: None)  # OpenBao 불통
    with pytest.raises(secret_source.SecretSourceError):
        secret_source.hydrate_from_vault()


def test_failure_without_required_warns_and_falls_back(monkeypatch, capsys):
    """강제 모드가 아니면 폴백하되, 조용히 넘어가지 않고 경고를 남긴다."""
    monkeypatch.setenv("CT_SECRET_MODE", "vault")
    monkeypatch.delenv("CT_SECRET_REQUIRED", raising=False)
    monkeypatch.setenv("CT_VAULT_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_VAULT_KV_PATH", "p")
    monkeypatch.setenv("CT_VAULT_TOKEN", "tkn")
    monkeypatch.setattr(secret_source, "_fetch_kv", lambda *a: None)
    secret_source.hydrate_from_vault()  # 기동은 계속됨
    assert "env 폴백" in capsys.readouterr().err
