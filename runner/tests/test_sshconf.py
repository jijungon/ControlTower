"""~/.ssh/config 파서 테스트 — 따옴표 제거·와일드카드 제외·ProxyJump."""
from runner.sshconf import parse_ssh_config

SAMPLE = '''
# 코멘트
Host *
  User nobody

Host web-01
  HostName 10.0.0.1
  User deploy
  IdentityFile "~/.ssh/aws-key/loopvm.pem"
  Port 22

Host app-01
  HostName=10.0.0.2
  User=ec2-user
  IdentityFile ~/.ssh/plain.pem
  ProxyJump gw

Host gw
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


def test_wildcard_excluded(tmp_path):
    hosts = {h.alias: h for h in parse_ssh_config(_write(tmp_path, SAMPLE))}
    assert "*" not in hosts  # Host * 는 제외


def test_key_value_and_proxyjump(tmp_path):
    hosts = {h.alias: h for h in parse_ssh_config(_write(tmp_path, SAMPLE))}
    assert hosts["app-01"].hostname == "10.0.0.2"  # Key=value 형식
    assert hosts["app-01"].user == "ec2-user"
    assert hosts["app-01"].proxy_jump == "gw"
