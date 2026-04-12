import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pprint
import httpx
from dotenv import load_dotenv

from agents.archive_agent.notion.agent import ArchiveAgent
from agents.archive_agent.models import ParsedTask

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
def archive_agent() -> ArchiveAgent:
    """ArchiveAgent 인스턴스를 반환하는 pytest 픽스처"""
    return ArchiveAgent()

@pytest.mark.asyncio
async def test_agent_initialization(archive_agent: ArchiveAgent) -> None:
    """.env 등을 통해 로드된 키 값으로 초기화가 정상적으로 되는지 확인"""
    assert archive_agent.agent_name == "archive_agent"
    assert archive_agent._token == os.environ["NOTION_TOKEN"]
    assert archive_agent._database_id == os.environ["NOTION_DATABASE_ID"]
    assert archive_agent._headers["Authorization"] == f"Bearer {os.environ['NOTION_TOKEN']}"
    assert archive_agent._headers["Notion-Version"] == "2022-06-28"

@pytest.mark.asyncio
async def test_fetch_pending_tasks_real(archive_agent: ArchiveAgent) -> None:
    """실제로 Notion API를 호출하여 '검토중' 상태인 작업을 원격으로 가져오는지 확인하는 통합 테스트"""
    # dummy_test_token인 경우 실행 시 에러가 나므로 건너뜁니다
    if archive_agent._token == "dummy_test_token" or archive_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")

    # 실제 api와 통신
    tasks = await archive_agent.fetch_pending_tasks()

    # 통신이 성공했다면 (배열 형태로 반환)
    assert isinstance(tasks, list)

    # 데이터베이스에 '검토중'인 작업이 있다면 id 등이 정상적으로 파싱되는지 검증
    if len(tasks) > 0:
        assert "id" in tasks[0]
    else:
        print("데이터베이스에 작업이 없습니다.")

@pytest.mark.asyncio
async def test_process_task(archive_agent: ArchiveAgent) -> None:
    """process_task 메서드가 정상적으로 데이터를 처리하는지 확인"""
    sample_task: ParsedTask = {
        "page_id": "test_page_123",
        "title": "테스트 제목",
        "description": "테스트 목적 설명",
        "status": "검토중"
    }

    with patch.object(archive_agent, 'update_notion_task', new_callable=AsyncMock) as mock_update:
        mock_update.return_value = (True, "mocked update")
        success, message = await archive_agent.process_task(sample_task)

    assert success is True
    assert "test_page_123" in message

@pytest.mark.asyncio
async def test_full_pipeline_with_real_data(archive_agent: ArchiveAgent) -> None:
    """
    실제 Notion DB에 기획 태스크를 생성하고,
    process_task를 통해 MD 파일 생성 + Notion 업데이트까지
    전 과정을 end-to-end로 검증하는 풀 테스트입니다.
    """
    if archive_agent._token == "dummy_test_token" or archive_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")

    # ── STEP 1: 실제 기획 데이터를 Notion에 생성 ──────────────────────────────
    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": archive_agent._database_id},
        "properties": {
            "제목": {
                "title": [{"text": {"content": "[E2E TEST] AI 코드 리뷰 에이전트 설계"}}]
            },
            "현황": {
                "status": {"name": "검토중"}
            },
            "목적": {
                "rich_text": [{
                    "text": {
                        "content": (
                            "개발자가 PR을 올리면 LLM이 자동으로 코드 품질, "
                            "보안 취약점, 컨벤션 준수 여부를 리뷰하고 GitHub PR에 코멘트를 달아주는 에이전트를 설계한다."
                        )
                    }
                }]
            },
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=archive_agent._headers, json=body)
        assert response.status_code == 200, f"노션 태스크 생성 실패: {response.text}"
        page_id: str = response.json()["id"]

    print(f"\n[STEP 1] Notion 태스크 생성 완료. Page ID: {page_id}")

    # ── STEP 2: ParsedTask로 변환하여 process_task 실행 ───────────────────────
    from agents.archive_agent.models import ParsedTask
    sample_task: ParsedTask = {
        "page_id": page_id,
        "title": "[E2E TEST] AI 코드 리뷰 에이전트 설계",
        "description": (
            "개발자가 PR을 올리면 LLM이 자동으로 코드 품질, "
            "보안 취약점, 컨벤션 준수 여부를 리뷰하고 GitHub PR에 코멘트를 달아주는 에이전트를 설계한다."
        ),
        "status": "검토중",
        "github_pr": "",
        "design_doc": "",
        "agent_assignees": ["archive_agent"],
        "assignees": [],
        "skeleton_code": "",
        "priority": "P1",
        "last_edited_time": "",
        "task_type": "새 프로젝트",
    }

    success, message = await archive_agent.process_task(sample_task)
    print(f"[STEP 2] process_task 결과: success={success}, message={message}")

    # ── STEP 3: 생성된 MD 파일 검증 ──────────────────────────────────────────
    import os
    md_path = f"task_{page_id}.md"
    assert os.path.exists(md_path), f"MD 파일이 생성되지 않았습니다: {md_path}"
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    print(f"\n[STEP 3] 생성된 MD 파일 내용:\n{'='*60}\n{content}\n{'='*60}")

    assert "1. 목표" in content, "목표 섹션 없음"
    assert "2. 과정" in content, "과정 섹션 없음"
    assert "3. 결과" in content, "결과 섹션 없음"
    assert "기능" in content, "기능 항목 없음"
    assert "기능들의 조립도" in content, "조립도 항목 없음"
    assert "출력" in content, "출력 항목 없음"

    # ── STEP 4: Notion에 정상 업데이트되었는지 확인 ──────────────────────────
    assert success is True, f"Notion 업데이트 실패: {message}"
    print(f"[STEP 4] Notion 업데이트 성공. 상태: 승인 대기중 전환 완료.")

@pytest.mark.asyncio
async def test_update_real_task_in_notion(archive_agent: ArchiveAgent) -> None:
    """실제로 Notion 데이터베이스에 있는 작업의 속성을 업데이트 하는 테스트"""
    if archive_agent._token == "dummy_test_token" or archive_agent._token is None:
        pytest.skip(".env에 실제 NOTION_TOKEN이 설정되지 않아 통신 테스트를 생략합니다.")

    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": archive_agent._database_id},
        "properties": {
            "제목": {"title": [{"text": {"content": "[Test] 업데이트 테스트 기획 태스크"}}]},
            "현황": {"status": {"name": "검토중"}}
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=archive_agent._headers, json=body)
        assert response.status_code == 200, "테스트용 태스크 생성 실패"
        page_id = response.json()["id"]

    success, message = await archive_agent.update_notion_task(
        page_id=page_id,
        status="검토중",
        agent_names=["Archive"],
        design_doc="자동 생성된 기획안 테스트 내용입니다.",
        skeleton_code="print('Hello World')",
        github_pr_url="https://github.com/test/repo/pull/1"
    )

    assert success is True, f"업데이트 실패: {message}"
    print(f"\n노션 태스크 업데이트 성공: {message}")

@pytest.mark.asyncio
async def test_run(archive_agent: ArchiveAgent) -> None:
    """run 메서드가 정상적으로 동작하는지 확인"""
    await archive_agent.run()
