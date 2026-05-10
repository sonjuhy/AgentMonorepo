import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pprint
import httpx
from dotenv import load_dotenv

from agents.archive_agent.notion.agent import ArchiveAgent
from agents.archive_agent.models import ParsedTask

# 프로젝트 루트의 .env 파일 로드
load_dotenv(encoding="utf-8", override=True)

# .env에 NOTION_DATABASE_ID 대신 NOTION_DB_ID만 있는 경우를 위한 Fallback
if "NOTION_DATABASE_ID" not in os.environ and "NOTION_DB_ID" in os.environ:
    os.environ["NOTION_DATABASE_ID"] = os.environ["NOTION_DB_ID"]

# 테스트 실행을 위해 필수 환경변수가 비어있다면 임시값 할당 (모킹 처리용)
if "NOTION_TOKEN" not in os.environ:
    os.environ["NOTION_TOKEN"] = "dummy_token"
if "NOTION_DATABASE_ID" not in os.environ:
    os.environ["NOTION_DATABASE_ID"] = "dummy_db_id"
if not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = "dummy_anthropic_key"
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
    assert (
        archive_agent._headers["Authorization"]
        == f"Bearer {os.environ['NOTION_TOKEN']}"
    )
    assert archive_agent._headers["Notion-Version"] == "2022-06-28"


@pytest.mark.asyncio
async def test_run(archive_agent: ArchiveAgent) -> None:
    """run 메서드가 정상적으로 동작하는지 확인"""
    await archive_agent.run()
