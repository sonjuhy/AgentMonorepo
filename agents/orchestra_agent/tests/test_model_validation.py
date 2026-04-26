import pytest
from pydantic import ValidationError

from agents.orchestra_agent.main import (
    SubmitTaskBody,
    LLMKeyUpdateBody,
    DirectDispatchBody,
    AgentLogBody,
)

def test_submit_task_body_max_length():
    # Valid content
    SubmitTaskBody(content="Short content")
    
    # Invalid content (too long, over 10000 chars)
    long_content = "a" * 10001
    with pytest.raises(ValidationError) as exc_info:
        SubmitTaskBody(content=long_content)
    assert "String should have at most 10000 characters" in str(exc_info.value) or "at most" in str(exc_info.value)

def test_llm_key_update_body_max_length():
    # Valid key
    LLMKeyUpdateBody(api_key="sk-normal-key")
    
    # Invalid key (too long, over 300 chars)
    long_key = "a" * 301
    with pytest.raises(ValidationError) as exc_info:
        LLMKeyUpdateBody(api_key=long_key)
    assert "at most" in str(exc_info.value)

def test_direct_dispatch_body_max_length():
    long_content = "a" * 10001
    with pytest.raises(ValidationError):
        DirectDispatchBody(agent_name="agent", action="do", content=long_content)

def test_agent_log_body_max_length():
    long_message = "a" * 5001
    with pytest.raises(ValidationError):
        AgentLogBody(agent_name="agent", action="do", message=long_message)
