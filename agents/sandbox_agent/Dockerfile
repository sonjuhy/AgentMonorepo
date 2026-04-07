FROM python:3.12-slim

WORKDIR /app

# iproute2: TAP 네트워크 설정 (ip tuntap)
# iptables: 격리 규칙 설정
RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iptables \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/agents/sandbox_agent/

ENV PYTHONPATH=/app
ENV MODE=server
ENV HOST=0.0.0.0
ENV PORT=8003

# 런타임 환경변수 (컨테이너 실행 시 주입 필요)
# REDIS_URL=redis://redis:6379
# ORCHESTRA_URL=http://orchestra-agent:8001
# SANDBOX_RUNTIME=docker          (firecracker | docker, 미설정 시 /dev/kvm 자동 감지)
# SANDBOX_DOCKER_IMAGE=python:3.12-alpine
# VM_POOL_MIN_READY=3
# VM_POOL_MAX_SIZE=10
#
# Firecracker 전용 (SANDBOX_RUNTIME=firecracker 시 필요)
# FIRECRACKER_BIN=/usr/local/bin/firecracker
# FIRECRACKER_KERNEL=/opt/firecracker/vmlinux
# FIRECRACKER_ROOTFS=/opt/firecracker/rootfs.ext4

EXPOSE 8003

CMD ["python", "-m", "agents.sandbox_agent.main"]
