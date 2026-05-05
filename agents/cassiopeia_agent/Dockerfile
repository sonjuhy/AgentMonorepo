FROM python:3.12-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r agents/cassiopeia_agent/requirements.txt

EXPOSE 49152

CMD ["python", "-m", "agents.cassiopeia_agent.main"]
