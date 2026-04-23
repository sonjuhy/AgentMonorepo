FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성 + Docker CLI (SandboxTool DockerSandbox 내부 실행용)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# 패키지 설치 (빌드 컨텍스트: 모노레포 루트)
COPY agents/orchestra_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사 — orchestra_agent (sandbox 패키지 포함) + 공유 코어
COPY agents/orchestra_agent/ /app/agents/orchestra_agent/
COPY shared_core/            /app/shared_core/

# 패키지 루트 설정 (agents 네임스페이스 패키지)
WORKDIR /app

ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8001

# 환경 변수 (런타임 주입 필요)
# REDIS_URL=redis://redis:6379
# GEMINI_API_KEY=...
# ANTHROPIC_API_KEY=...          (optional, Claude fallback NLU)
# SANDBOX_RUNTIME=docker         (docker | firecracker, 기본 자동 감지)
# NLU_LLM_MODEL=gemini-2.0-flash
# VM_POOL_MIN_READY=3
# VM_POOL_MAX_SIZE=10

EXPOSE 8001

CMD ["python", "-m", "agents.orchestra_agent.main"]
