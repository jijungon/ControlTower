"""접속 어댑터(access) + 서명기(signer) 단위 테스트 — OpenBao 없이 검증.

핵심: 기본(key) 모드는 기존과 동일(추가 옵션 없음). cert 모드는 서명된 인증서 옵션을 끼운다.
서명 미설정/실패면 key 로 폴백.
"""
import json

from runner import access, conn, signer


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

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            return json.dumps(self._p).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        captured["token"] = req.get_header("X-vault-token")
        captured["body"] = json.loads(req.data.decode())
        return FakeResp({"data": {"signed_key": "CERT-DATA"}})

    monkeypatch.setattr(signer.urllib.request, "urlopen", fake_urlopen)

    key = tmp_path / "id"
    cert = signer._sign("ssh-ed25519 AAAA pub", str(key))

    assert cert == str(key) + "-cert.pub"
    assert (tmp_path / "id-cert.pub").read_text() == "CERT-DATA"
    assert captured["url"].endswith("/v1/ssh-client-signer/sign/runner-ro")
    assert captured["token"] == "root"
    assert captured["body"]["public_key"] == "ssh-ed25519 AAAA pub"
