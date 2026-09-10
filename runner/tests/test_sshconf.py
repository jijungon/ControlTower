"""ssh config 파서 테스트."""
from runner.sshconf import parse_ssh_config

SAMPLE = """
# 코멘트
Host bastion
    HostName 10.0.0.1
    User ops
    IdentityFile ~/.ssh/gw_ed25519

Host web-*
    User deploy

Host web-01
    HostName 10.0.1.10
    User deploy
    Port 2222
    ProxyJump bastion
    IdentityFile ~/.ssh/svc_ed25519
"""


def test_parse(tmp_path):
    f = tmp_path / "config"
    f.write_text(SAMPLE)
    by = {h.alias: h for h in parse_ssh_config(str(f))}

    assert "bastion" in by and "web-01" in by
    assert "web-*" not in by  # 와일드카드 Host 제외
    assert by["web-01"].hostname == "10.0.1.10"
    assert by["web-01"].user == "deploy"
    assert by["web-01"].port == 2222
    assert by["web-01"].proxy_jump == "bastion"
    assert by["web-01"].identity_file.endswith("svc_ed25519")


def test_missing_file(tmp_path):
    assert parse_ssh_config(str(tmp_path / "none")) == []
