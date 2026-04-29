import pytest
from unittest.mock import AsyncMock, patch
from agents.communication_agent.slack.notion_parser import parse_notion_task

def test_parse_notion_task_valid():
    raw_payload = {
        "id": "page-123",
        "properties": {
            "제목": {"title": [{"plain_text": "Test Task"}]},
            "목적": {"rich_text": [{"plain_text": "description"}]},
            "현황": {"status": {"name": "승인 대기중"}},
            "GitHub PR": {"url": "https://github.com/pr"},
            "기획안/설계도": {"rich_text": [{"plain_text": "design"}]},
            "담당 에이전트": {"multi_select": [{"name": "agent1"}]},
            "담당자": {"people": [{"name": "user1"}]},
            "스켈레톤 코드": {"rich_text": [{"plain_text": "code"}]},
            "우선순위": {"select": {"name": "높음"}},
            "최종 실행 시간": {"last_edited_time": "2023-01-01T00:00:00Z"},
            "타입": {"select": {"name": "Feature"}}
        }
    }
    task = parse_notion_task(raw_payload)
    assert task is not None
    assert task["title"] == "Test Task"
    assert task["description"] == "description"
    assert task["status"] == "승인 대기중"
    assert task["github_pr"] == "https://github.com/pr"
    assert task["design_doc"] == "design"
    assert task["agent_assignees"] == ["agent1"]
    assert task["assignees"] == ["user1"]
    assert task["skeleton_code"] == "code"
    assert task["priority"] == "높음"
    assert task["last_edited_time"] == "2023-01-01T00:00:00Z"
    assert task["task_type"] == "Feature"

def test_parse_notion_task_missing_title():
    raw_payload = {
        "id": "page-123",
        "properties": {
            "제목": {"title": []},
            "현황": {"status": {"name": "승인 대기중"}}
        }
    }
    task = parse_notion_task(raw_payload)
    # it still returns a task, but title is "제목 없음"
    assert task is not None
    assert task["title"] == "제목 없음"
