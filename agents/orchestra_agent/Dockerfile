FROM python:3.12-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . /app/agents/orchestra_agent/

# 패키지 루트 설정 (agents 네임스페이스 패키지)
WORKDIR /app

ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8001

# 환경 변수 (런타임 주입 필요)
# REDIS_URL=redis://redis:6379
# GEMINI_API_KEY=...
# ANTHROPIC_API_KEY=...          (optional, Claude fallback NLU)
# POSTGRES_URL=...               (optional, persistent session history)
# NLU_BACKEND=gemini             (gemini | claude)
# COMM_AGENT_URL=http://communication-agent:8000
# USER_TIMEZONE=Asia/Seoul
# AGENT_TIMEOUT_DEFAULT=120

EXPOSE 8001

CMD ["python", "-m", "agents.orchestra_agent.main"]
