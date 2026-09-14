# 연습용 미니 서버 — 진짜 SSH + 샘플 설정파일. 일회용(검증 끝나면 삭제).
# 운영 서버 대신 이 컨테이너로 conf apply(백업→교체→verify→롤백)를 실제로 검증한다.
FROM ubuntu:22.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-server ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd

# 연습용 접속 계정. 관리 파일을 이 계정 소유로 둬서 sudo 없이 교체 가능(첫 검증 단순화).
RUN useradd -m -s /bin/bash deploy

# 접속 키 등록 — authorized_keys 는 셋업 때 생성한 '연습용 공개키'로 채운다.
COPY authorized_keys /home/deploy/.ssh/authorized_keys
RUN chown -R deploy:deploy /home/deploy/.ssh \
 && chmod 700 /home/deploy/.ssh \
 && chmod 600 /home/deploy/.ssh/authorized_keys

# 관리 대상 설정파일(기준본과 동일하게 시작). deploy 소유 → sudo 불필요.
RUN mkdir -p /etc/demo
COPY nginx.conf /etc/demo/nginx.conf
RUN chown -R deploy:deploy /etc/demo

# 비밀번호 로그인 차단, 키 인증만 허용(연습이라도 안전하게).
RUN sed -i 's/#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config \
 && sed -i 's/#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
