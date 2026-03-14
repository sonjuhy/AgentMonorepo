import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pprint
import httpx
from dotenv import load_dotenv

from agents.planning_agent.agent import PlanningAgent
from agents.planning_agent.models import ParsedTask

# 프로젝트 루트의 .env 파일 로드
load_dotenv()

# .env에 NOTION_DATABASE_ID 대신 NOTION_DB_ID만 있는 경우를 위한 Fallback
if "NOTION_DATABASE_ID" not in os.environ and "NOTION_DB_ID" in os.environ:
    os.environ["NOTION_DATABASE_ID"] = os.environ["NOTION_DB_ID"]

# 테스트 실행을 위해 필수 환경변수가 비어있다면 임시값 할당 (모킹 처리용)
if "NOTION_TOKEN" not in os.environ:
    os.environ["NOTION_TOKEN"] = "dummy_test_token"
if "NOTION_DATABASE_ID" not in os.environ:
    os.environ["NOTION_DATABASE_ID"] = "dummy_test_db_id"

@pytest.fixture
def planning_agent() -> PlanningAgent:
    """PlanningAgent 인스턴스를 반환하는 pytest 픽스처"""
    return PlanningAgent()

@pytest.mark.asyncio
async def test_agent_initialization(planning_agent: PlanningAgent) -> None:
    """.env 등을 통해 로드된 키 값으로 초기화가 정상적으로 되는지 확인"""
    assert planning_agent.agent_name == "planning-agent"
    assert planning_agent._token == os.environ["NOTION_TOKEN"]
    assert planning_agent._database_id == os.environ["NOTION_DATABASE_ID"]
    assert planning_agent._headers["Authorization"] == f"Bearer {os.environ['NOTION_TOKEN']}"
    assert planning_agent._headers["Notion-Version"] == "2022-06-28"

@pytest.mark.asyncio
async def test_fetch_pending_tasks_real(planning_agent: PlanningAgent) -> None:
    """실제로 Notion API를 호출하여 '검토중' 상태인 작업을 원격으로 가져오는지 확인하는 통합 테스트"""
    # dummy_test_token인 경우 실행 시 에러가 나므로 건너뜁니다
    if planning_agent._token == "dummy_test_token" or planning_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")
        
    # 실제 api와 통신
    tasks = await planning_agent.fetch_pending_tasks()
    
    # 통신이 성공했다면 (배열 형태로 반환)
    assert isinstance(tasks, list)

    # 데이터베이스에 '검토중'인 작업이 있다면 id 등이 정상적으로 파싱되는지 검증
    if len(tasks) > 0:
        assert "id" in tasks[0]
    else:
        print("데이터베이스에 작업이 없습니다.")

@pytest.mark.asyncio
async def test_process_task(planning_agent: PlanningAgent) -> None:
    """process_task 메서드가 정상적으로 데이터를 처리하는지 확인"""
    sample_task: ParsedTask = {
        "page_id": "test_page_123",
        "title": "테스트 제목",
        "description": "테스트 목적 설명",
        "status": "검토중"
    }
    
    success, message = await planning_agent.process_task(sample_task)
    
    assert success is True
    assert "test_page_123" in message

@pytest.mark.asyncio
async def test_create_real_task_in_notion(planning_agent: PlanningAgent) -> None:
    """실제로 Notion 데이터베이스에 새로운 작업을 생성하는 테스트"""
    if planning_agent._token == "dummy_test_token" or planning_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")

    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": planning_agent._database_id},
        "properties": {
            "제목": {
                "title": [{"text": {"content": "[Test] 자동 생성된 테스트 기획 태스크"}}]
            },
            "현황": {
                "status": {"name": "검토중"}
            },
            "목적": {
                "rich_text": [{"text": {"content": "Notion API 쓰기 테스트용 자동 생성 데이터입니다."}}]
            },
            "타입": {
                "select": {"name": "새 프로젝트"}
            },
            "우선순위": {
                "select": {"name": "P0"}
            }
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=planning_agent._headers, json=body)
        
        assert response.status_code == 200, f"노션 쓰기 실패: {response.text}"
        data = response.json()
        assert "id" in data
        print(f"\n새로운 노션 태스크 생성 완료. Page ID: {data['id']}")

@pytest.mark.asyncio
async def test_update_real_task_in_notion(planning_agent: PlanningAgent) -> None:
    """실제로 Notion 데이터베이스에 있는 작업의 속성을 업데이트 하는 테스트"""
    if planning_agent._token == "dummy_test_token" or planning_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")
        
    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": planning_agent._database_id},
        "properties": {
            "제목": {"title": [{"text": {"content": "[Test] 업데이트 테스트 기획 태스크"}}]},
            "현황": {"status": {"name": "검토중"}}
        }
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=planning_agent._headers, json=body)
        assert response.status_code == 200, "테스트용 태스크 생성 실패"
        page_id = response.json()["id"]
        
    success, message = await planning_agent.update_notion_task(
        page_id=page_id,
        status="검토중",
        agent_names=["Planning"],
        design_doc="자동 생성된 기획안 테스트 내용입니다.",
        skeleton_code="print('Hello World')",
        github_pr_url="https://github.com/test/repo/pull/1"
    )
    
    assert success is True, f"업데이트 실패: {message}"
    print(f"\n노션 태스크 업데이트 성공: {message}")

@pytest.mark.asyncio
async def test_run(planning_agent: PlanningAgent) -> None:
    """run 메서드가 정상적으로 동작하는지 확인"""
    await planning_agent.run()
