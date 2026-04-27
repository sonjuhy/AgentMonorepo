import pytest
from agents.sandbox_agent.sandbox.docker_sandbox import DockerSandbox
from agents.sandbox_agent.sandbox.models import ExecuteRequest

def test_docker_sandbox_env_whitelist():
    sandbox = DockerSandbox()
    
    # 허용되지 않은 환경변수 포함 요청
    req = ExecuteRequest(
        language="python",
        code="print(1)",
        env={
            "ALLOWED_VAR": "value",
            "DANGEROUS_VAR": "secret",
            "PATH": "/evil/path"
        }
    )
    
    cmd = sandbox._build_cmd(req)
    cmd_str = " ".join(cmd)
    
    # 검증: ALLOWED_VAR는 포함되어야 함
    # DANGEROUS_VAR와 PATH는 차단되어야 함
    
    assert "-e ALLOWED_VAR=value" in cmd_str
    assert "-e DANGEROUS_VAR=secret" not in cmd_str
    assert "-e PATH=/evil/path" not in cmd_str

def test_docker_sandbox_env_prefixes():
    sandbox = DockerSandbox()
    
    req = ExecuteRequest(
        language="python",
        code="print(1)",
        env={
            "SB_DATA": "some_data",
            "USER_ID": "123",
            "OTHER_VAR": "blocked"
        }
    )
    
    cmd = sandbox._build_cmd(req)
    cmd_str = " ".join(cmd)
    
    assert "-e SB_DATA=some_data" in cmd_str
    assert "-e USER_ID=123" in cmd_str
    assert "-e OTHER_VAR=blocked" not in cmd_str
