"""~/.ssh/config 파서 테스트 — 따옴표 제거·와일드카드 제외·Port·ProxyJump·없는 파일."""
from runner.sshconf import parse_ssh_config

SAMPLE = '''
# 코멘트
Host *
  User nobody

Host web-*
  User deploy

Host web-01
  HostName 10.0.0.1
  User deploy
  Port 2222
  IdentityFile "~/.ssh/aws-key/loopvm.pem"
  ProxyJump bastion

Host app-01
  HostName=10.0.0.2
  User=ec2-user
  IdentityFile ~/.ssh/plain.pem

Host bastion
  HostName 1.2.3.4
'''


def _write(tmp_path, text):
    p = tmp_path / "config"
    p.write_text(text)
    return str(p)


def test_dequote_identityfile(tmp_path):
    hosts = {h.alias: h for h in parse_ssh_config(_write(tmp_path, SAMPLE))}
    # 따옴표 감싼 IdentityFile → 따옴표 없이 파싱
    assert hosts["web-01"].identity_file == "~/.ssh/aws-key/loopvm.pem"
    # 따옴표 없는 것도 그대로
    assert hosts["app-01"].identity_file == "~/.ssh/plain.pem"


def test_wildcards_excluded(tmp_path):
    hosts = {h.alias: h for h in parse_ssh_config(_write(tmp_path, SAMPLE))}
    assert "*" not in hosts and "web-*" not in hosts  # 와일드카드 Host 제외


def test_fields_and_proxyjump(tmp_path):
    hosts = {h.alias: h for h in parse_ssh_config(_write(tmp_path, SAMPLE))}
    w = hosts["web-01"]
    assert w.hostname == "10.0.0.1" and w.user == "deploy"
    assert w.port == 2222 and w.proxy_jump == "bastion"
    # Key=value 형식
    assert hosts["app-01"].hostname == "10.0.0.2" and hosts["app-01"].user == "ec2-user"


def test_missing_file(tmp_path):
    assert parse_ssh_config(str(tmp_path / "none")) == []
