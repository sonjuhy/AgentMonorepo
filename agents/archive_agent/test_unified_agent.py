import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from agents.archive_agent.unified_agent import UnifiedArchiveAgent
from shared_core.llm.interfaces import LLMUsage

@pytest.fixture
def mock_llm_provider():
    provider = AsyncMock()
    # 기본 모의 응답: Notion 검색
    provider.generate_response.return_value = (
        '{"target": "notion", "action": "search", "query": "로그인 기획안", "reasoning": "노션에서 기획안 검색 요청"}',
        LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )
    return provider

@pytest.fixture
def unified_agent(mock_llm_provider, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake_anthropic_key")
    monkeypatch.setenv("NOTION_TOKEN", "fake_notion_token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "fake_db_id")
    with patch("agents.archive_agent.unified_agent.build_llm_provider_from_config", return_value=mock_llm_provider):
        agent = UnifiedArchiveAgent()
        # 하위 에이전트 모킹 (실제 호출 방지)
        agent.notion_agent.handle_dispatch = AsyncMock(return_value={"status": "notion_success"})
        agent.obsidian_agent.handle_dispatch = AsyncMock(return_value={"status": "obsidian_success"})
        return agent

@pytest.mark.asyncio
async def test_routing_explicit_source_notion(unified_agent, mock_llm_provider):
    """params에 source가 명시되어 있으면 LLM을 타지 않고 바로 해당 에이전트로 라우팅"""
    msg = {"content": "결제 스펙 찾아줘", "params": {"source": "notion"}}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "notion_success"
    mock_llm_provider.generate_response.assert_not_called()
    unified_agent.notion_agent.handle_dispatch.assert_called_once()

@pytest.mark.asyncio
async def test_routing_explicit_source_obsidian(unified_agent, mock_llm_provider):
    """params에 source가 명시되어 있으면 LLM을 타지 않고 바로 해당 에이전트로 라우팅"""
    msg = {"content": "로컬 파일 찾아줘", "params": {"source": "obsidian"}}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "obsidian_success"
    mock_llm_provider.generate_response.assert_not_called()
    unified_agent.obsidian_agent.handle_dispatch.assert_called_once()

@pytest.mark.asyncio
async def test_routing_llm_decision_obsidian(unified_agent, mock_llm_provider):
    """LLM이 obsidian으로 판단한 경우"""
    mock_llm_provider.generate_response.return_value = (
        '```json\n{"target": "obsidian", "action": "read_file", "query": "로컬메모", "reasoning": "옵시디언 멘션"}\n```',
        LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )
    
    msg = {"content": "내 로컬 메모장 읽어줘"}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "obsidian_success"
    mock_llm_provider.generate_response.assert_called_once()
    unified_agent.obsidian_agent.handle_dispatch.assert_called_once()
    
    # params에 LLM이 추출한 query와 action이 들어갔는지 확인
    call_args = unified_agent.obsidian_agent.handle_dispatch.call_args[0][0]
    assert call_args["params"]["action"] == "read_file"
    assert call_args["params"]["query"] == "로컬메모"

@pytest.mark.asyncio
async def test_routing_llm_fallback(unified_agent, mock_llm_provider):
    """LLM이 오류를 뱉으면 룰백 로직을 사용함"""
    mock_llm_provider.generate_response.side_effect = Exception("LLM Error")
    
    # "옵시디언" 키워드가 있으므로 fallback 로직에 의해 obsidian으로 빠져야 함
    msg = {"content": "옵시디언에서 찾아줘"}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "obsidian_success"
    unified_agent.obsidian_agent.handle_dispatch.assert_called_once()

@pytest.mark.asyncio
async def test_routing_empty_request_fails(unified_agent, mock_llm_provider):
    """요청 내용과 파라미터가 모두 비어있는 경우 즉시 FAILED 응답을 반환해야 함"""
    msg = {"task_id": "test_empty_123", "content": "  ", "params": {}}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "FAILED"
    assert res["error"]["code"] == "INVALID_REQUEST"
    mock_llm_provider.generate_response.assert_not_called()
    unified_agent.notion_agent.handle_dispatch.assert_not_called()
    unified_agent.obsidian_agent.handle_dispatch.assert_not_called()

@pytest.mark.asyncio
async def test_routing_llm_decision_unknown(unified_agent, mock_llm_provider):
    """LLM이 'unknown'으로 타겟을 지정한 엉뚱한 요청의 경우 즉시 FAILED 응답을 반환해야 함"""
    mock_llm_provider.generate_response.return_value = (
        '{"target": "unknown", "reasoning": "문서 작업과 관련 없는 배달 음식 추천 요청임"}',
        LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )
    
    msg = {"task_id": "test_unknown_456", "content": "오늘 점심 메뉴 좀 추천해줘"}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "FAILED"
    assert res["error"]["code"] == "UNSUPPORTED_REQUEST"
    mock_llm_provider.generate_response.assert_called_once()
    unified_agent.notion_agent.handle_dispatch.assert_not_called()
    unified_agent.obsidian_agent.handle_dispatch.assert_not_called()

@pytest.mark.asyncio
async def test_routing_chatty_llm_response(unified_agent, mock_llm_provider):
    """LLM이 앞뒤로 수다스러운 텍스트를 붙여도 JSON만 정확히 추출하는지 테스트"""
    mock_llm_provider.generate_response.return_value = (
        '네, 알겠습니다. 분석 결과는 다음과 같습니다.\\n```json\\n{"target": "obsidian", "action": "read_file", "query": "회의록", "reasoning": "로컬 회의록"}\\n```\\n도움이 되셨길 바랍니다!',
        LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )
    
    msg = {"task_id": "test_chatty_123", "content": "어제 회의록 읽어줘"}
    res = await unified_agent.handle_dispatch(msg)
    
    assert res["status"] == "obsidian_success"
    unified_agent.obsidian_agent.handle_dispatch.assert_called_once()

@pytest.mark.asyncio
async def test_routing_empty_content_but_has_params(unified_agent, mock_llm_provider):
    """content 없이 params만 있는 명시적 요청의 경우 LLM을 거치지 않고 기본 라우팅(Notion)을 타는지 테스트"""
    msg = {"task_id": "test_params_only", "content": "", "params": {"database_id": "1234", "action": "query_database"}}
    res = await unified_agent.handle_dispatch(msg)
    
    # 기본값인 notion으로 라우팅되어야 함
    assert res["status"] == "notion_success"
    mock_llm_provider.generate_response.assert_not_called()
    unified_agent.notion_agent.handle_dispatch.assert_called_once()

@pytest.mark.asyncio
async def test_routing_llm_hallucination_target(unified_agent, mock_llm_provider):
    """LLM이 규칙에 없는 이상한 target을 반환했을 때, 안전하게 기본값(Notion)으로 라우팅되는지 테스트"""
    mock_llm_provider.generate_response.return_value = (
        '{"target": "evernote", "action": "search", "query": "아이디어", "reasoning": "에버노트 검색"}',
        LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )
    
    msg = {"task_id": "test_hallucination", "content": "내 아이디어 노트 찾아줘"}
    res = await unified_agent.handle_dispatch(msg)
    
    # 알 수 없는 target이므로 else 구문을 타서 notion으로 라우팅됨
    assert res["status"] == "notion_success"
    unified_agent.notion_agent.handle_dispatch.assert_called_once()
