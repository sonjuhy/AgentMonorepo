FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성 및 보안 유저 생성
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appgroup && useradd -r -g appgroup -s /sbin/nologin appuser

# 패키지 설치
COPY agents/sandbox_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사 및 권한 설정
COPY agents/sandbox_agent/ /app/agents/sandbox_agent/
COPY shared_core/            /app/shared_core/
# sandbox_agent는 docker 소켓 접근을 위해 특정 권한이 필요할 수 있으나, 
# 기본적으로 앱 실행은 일반 유저로 시도하고 소켓 권한은 group 설정으로 제어합니다.
RUN chown -R appuser:appgroup /app

USER appuser

ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8003

# 샌드박스 런타임 설정 (기본 docker)
ENV SANDBOX_RUNTIME=docker
ENV VM_POOL_MIN_READY=2
ENV VM_POOL_MAX_SIZE=10

EXPOSE 8003

CMD ["python", "-m", "agents.sandbox_agent.main"]
