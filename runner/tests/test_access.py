"""접속 어댑터(access) + 서명기(signer) 단위 테스트 — OpenBao 없이 검증.

핵심: 기본(key) 모드는 기존과 동일(추가 옵션 없음). cert 모드는 서명된 인증서 옵션을 끼운다.
서명 미설정/실패면 key 로 폴백.
"""
import json

import pytest

from runner import access, conn, signer


class FakeResp:
    """urlopen 응답 대역 — with 문으로 열고 JSON 바디를 돌려준다."""

    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_default_is_key_mode(monkeypatch):
    monkeypatch.delenv("CT_SSH_MODE", raising=False)
    assert access.ssh_mode() == "key"
    assert access.ssh_access_opts("web-01") == []


def test_cert_mode_unconfigured_falls_back_to_key(monkeypatch):
    monkeypatch.setenv("CT_SSH_MODE", "cert")
    monkeypatch.delenv("CT_BAO_ADDR", raising=False)  # OpenBao 미설정
    signer.reset_cache()
    assert access.ssh_access_opts("web-01") == []  # 서명 불가 → key 폴백


def test_cert_mode_with_signer(monkeypatch):
    monkeypatch.setenv("CT_SSH_MODE", "cert")
    monkeypatch.setattr(signer, "ensure_cert", lambda alias: ("/home/u/.ssh/id", "/home/u/.ssh/id-cert.pub"))
    assert access.ssh_access_opts("web-01") == [
        "-i", "/home/u/.ssh/id",
        "-o", "CertificateFile=/home/u/.ssh/id-cert.pub",
    ]


def test_ssh_argv_key_mode_unchanged(monkeypatch):
    monkeypatch.delenv("CT_SSH_MODE", raising=False)
    argv = conn._ssh_argv("web-01", 8)
    assert argv[0] == "ssh" and argv[-1] == "web-01"
    assert "BatchMode=yes" in argv
    assert "CertificateFile" not in " ".join(argv)  # key 모드엔 인증서 옵션 없음


def test_ssh_argv_cert_mode_injects_cert(monkeypatch):
    monkeypatch.setenv("CT_SSH_MODE", "cert")
    monkeypatch.setattr(signer, "ensure_cert", lambda alias: ("/k", "/k-cert.pub"))
    argv = conn._ssh_argv("web-01", 8)
    joined = " ".join(argv)
    assert "-i /k" in joined and "CertificateFile=/k-cert.pub" in joined
    assert argv[-1] == "web-01"  # 옵션은 alias 앞


def test_signer_caches_and_gates(monkeypatch, tmp_path):
    signer.reset_cache()
    key = tmp_path / "id"
    (tmp_path / "id.pub").write_text("ssh-ed25519 AAAA test")
    calls = {"n": 0}

    def fake_sign(pub, keyp):
        calls["n"] += 1
        return keyp + "-cert.pub"

    monkeypatch.setenv("CT_BAO_ADDR", "https://bao.local")
    monkeypatch.setenv("CT_SSH_KEY", str(key))
    monkeypatch.setattr(signer, "_sign", fake_sign)

    first = signer.ensure_cert("a")
    second = signer.ensure_cert("b")
    assert first == second        # 프로세스 캐시 재사용
    assert calls["n"] == 1         # 서명은 1회만(서버마다 다시 안 함)
    assert first[0] == str(key)


def test_signer_unconfigured_returns_none(monkeypatch):
    signer.reset_cache()
    monkeypatch.delenv("CT_BAO_ADDR", raising=False)
    assert signer.ensure_cert("a") is None


def test_signer_sign_via_http(monkeypatch, tmp_path):
    """_sign 이 bao CLI 아닌 HTTP(urllib)로 OpenBao 에 서명 요청하는지 검증."""
    signer.reset_cache()
    monkeypatch.setenv("CT_BAO_ADDR", "http://bao.local")
    monkeypatch.setenv("CT_BAO_TOKEN", "root")
    monkeypatch.delenv("CT_BAO_ROLE_ID", raising=False)
    monkeypatch.delenv("CT_BAO_SECRET_ID", raising=False)

    captured = {}

    def fake_urlopen(req, timeout=10, context=None):
        captured["url"] = req.full_url
        captured["token"] = req.get_header("X-vault-token")
        captured["body"] = json.loads(req.data.decode())
        captured["context"] = context
        return FakeResp({"data": {"signed_key": "CERT-DATA"}})

    monkeypatch.setattr(signer.urllib.request, "urlopen", fake_urlopen)

    key = tmp_path / "id"
    cert = signer._sign("ssh-ed25519 AAAA pub", str(key))

    assert cert == str(key) + "-cert.pub"
    assert (tmp_path / "id-cert.pub").read_text() == "CERT-DATA"
    assert captured["url"].endswith("/v1/ssh-client-signer/sign/runner-ro")
    assert captured["token"] == "root"
    assert captured["body"]["public_key"] == "ssh-ed25519 AAAA pub"
    assert captured["context"] is None  # http → 기존 경로 그대로


# ── TLS (사설 CA + mTLS) ──


class _FakeCtx:
    """ssl.SSLContext 대역 — 어떤 CA·클라이언트 인증서를 넣었는지만 기록."""

    def __init__(self, loaded, cafile):
        self.cafile, self._loaded = cafile, loaded

    def load_cert_chain(self, cert, key=None):
        self._loaded["chain"] = (cert, key)


def test_http_addr_gets_no_ssl_context(monkeypatch):
    """http 면 컨텍스트 None — PoC/개발 경로는 전혀 안 바뀐다."""
    monkeypatch.setenv("CT_BAO_ADDR", "http://bao.local:8200")
    monkeypatch.setenv("CT_BAO_CACERT", "/ignored.pem")
    assert signer._ssl_context() is None


def test_https_uses_private_ca_and_client_cert(monkeypatch, tmp_path):
    """https 면 사내 CA 를 신뢰하고 클라이언트 인증서(mTLS)를 붙인다."""
    ca, crt, key = tmp_path / "ca.pem", tmp_path / "c.crt", tmp_path / "c.key"
    for p in (ca, crt, key):
        p.write_text("")
    loaded = {}
    monkeypatch.setenv("CT_BAO_ADDR", "https://bao.local:8200")
    monkeypatch.setenv("CT_BAO_CACERT", str(ca))
    monkeypatch.setenv("CT_BAO_CLIENT_CERT", str(crt))
    monkeypatch.setenv("CT_BAO_CLIENT_KEY", str(key))
    monkeypatch.setattr(signer.ssl, "create_default_context", lambda cafile=None: _FakeCtx(loaded, cafile))
    ctx = signer._ssl_context()
    assert ctx.cafile == str(ca)
    assert loaded["chain"] == (str(crt), str(key))


def test_ssl_context_is_passed_to_urlopen(monkeypatch, tmp_path):
    """컨텍스트가 실제 요청에 전달되는지 — 빠지면 mTLS 가 조용히 무시된다."""
    signer.reset_cache()
    monkeypatch.setenv("CT_BAO_ADDR", "https://bao.local:8200")
    monkeypatch.delenv("CT_BAO_CACERT", raising=False)  # OS 기본 신뢰 저장소로 충분
    monkeypatch.delenv("CT_BAO_CLIENT_CERT", raising=False)
    monkeypatch.setenv("CT_BAO_TOKEN", "root")
    seen = {}

    def fake_urlopen(req, timeout=10, context=None):
        seen["context"] = context
        return FakeResp({"data": {"signed_key": "C"}})

    monkeypatch.setattr(signer.urllib.request, "urlopen", fake_urlopen)
    signer._sign("ssh-ed25519 AAAA pub", str(tmp_path / "id"))
    assert isinstance(seen["context"], signer.ssl.SSLContext)


# ── 조용한 폴백 방지 ──


def test_required_mode_raises_instead_of_silent_key_fallback(monkeypatch):
    """CT_SSH_CERT_REQUIRED=1 이면 서명 실패를 key 폴백으로 덮지 않는다."""
    signer.reset_cache()
    monkeypatch.setenv("CT_SSH_CERT_REQUIRED", "1")
    monkeypatch.delenv("CT_BAO_ADDR", raising=False)
    with pytest.raises(signer.SignerError):
        signer.ensure_cert("web-01")


def test_fallback_warns_once_not_per_host(monkeypatch, capsys):
    """폴백은 조용하지 않게 — 단, 서버 수만큼 반복 출력하지는 않는다."""
    signer.reset_cache()
    monkeypatch.delenv("CT_SSH_CERT_REQUIRED", raising=False)
    monkeypatch.delenv("CT_BAO_ADDR", raising=False)
    assert signer.ensure_cert("web-01") is None
    assert signer.ensure_cert("web-02") is None
    assert capsys.readouterr().err.count("key 모드로 폴백") == 1
