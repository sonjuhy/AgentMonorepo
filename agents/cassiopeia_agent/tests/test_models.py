"""
models.py — Pydantic 스키마 및 유틸리티 함수 테스트
"""
from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from agents.cassiopeia_agent.models import (
    AGENT_TIMEOUT_MAP,
    ClarificationNLUResult,
    DirectResponseNLUResult,
    MultiStepNLUResult,
    NLUMetadata,
    NLU_CONFIDENCE_THRESHOLD,
    PlanStep,
    PlanStepMetadata,
    SingleNLUResult,
    _build_timeout_map,
)


# ── NLUMetadata ───────────────────────────────────────────────────────────────

class TestNLUMetadata:
    def test_valid(self):
        m = NLUMetadata(reason="테스트", confidence_score=0.85, requires_user_approval=False)
        assert m.confidence_score == 0.85
        assert m.requires_user_approval is False

    def test_confidence_boundary_min(self):
        m = NLUMetadata(reason="low", confidence_score=0.0)
        assert m.confidence_score == 0.0

    def test_confidence_boundary_max(self):
        m = NLUMetadata(reason="high", confidence_score=1.0)
        assert m.confidence_score == 1.0

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            NLUMetadata(reason="bad", confidence_score=1.1)

    def test_confidence_negative(self):
        with pytest.raises(ValidationError):
            NLUMetadata(reason="bad", confidence_score=-0.1)

    def test_requires_approval_defaults_false(self):
        m = NLUMetadata(reason="r", confidence_score=0.5)
        assert m.requires_user_approval is False


# ── SingleNLUResult ───────────────────────────────────────────────────────────

class TestSingleNLUResult:
    def test_valid(self):
        r = SingleNLUResult(
            type="single",
            intent="파일 읽기",
            selected_agent="file_agent",
            action="read_file",
            params={"path": "/tmp/a.txt"},
            metadata={"reason": "r", "confidence_score": 0.9, "requires_user_approval": False},
        )
        assert r.type == "single"
        assert r.selected_agent == "file_agent"

    def test_wrong_type_literal(self):
        with pytest.raises(ValidationError):
            SingleNLUResult(
                type="multi_step",
                intent="x",
                selected_agent="file_agent",
                action="read_file",
                params={},
                metadata={"reason": "r", "confidence_score": 0.9, "requires_user_approval": False},
            )


# ── MultiStepNLUResult ────────────────────────────────────────────────────────

class TestMultiStepNLUResult:
    def test_valid(self):
        r = MultiStepNLUResult(
            type="multi_step",
            intent="복합 작업",
            plan=[
                {
                    "step": 1,
                    "selected_agent": "file_agent",
                    "action": "read_file",
                    "params": {},
                    "depends_on": [],
                    "metadata": {"reason": "r", "requires_user_approval": False},
                }
            ],
            metadata={"reason": "r", "confidence_score": 0.8, "requires_user_approval": False},
        )
        assert len(r.plan) == 1
        assert r.plan[0].step == 1

    def test_plan_step_depends_on_defaults_empty(self):
        step = PlanStep(
            step=1,
            selected_agent="file_agent",
            action="read_file",
            params={},
            metadata=PlanStepMetadata(reason="r"),
        )
        assert step.depends_on == []


# ── ClarificationNLUResult ────────────────────────────────────────────────────

class TestClarificationNLUResult:
    def test_valid(self):
        r = ClarificationNLUResult(
            type="clarification",
            intent="unclear",
            selected_agent="communication_agent",
            action="ask_clarification",
            params={"question": "무엇을 원하시나요?", "options": ["A", "B"]},
            metadata={"reason": "r", "confidence_score": 0.3, "requires_user_approval": False},
        )
        assert r.params.question == "무엇을 원하시나요?"
        assert r.params.options == ["A", "B"]

    def test_options_defaults_empty(self):
        r = ClarificationNLUResult(
            type="clarification",
            intent="unclear",
            selected_agent="communication_agent",
            action="ask_clarification",
            params={"question": "?"},
            metadata={"reason": "r", "confidence_score": 0.2, "requires_user_approval": False},
        )
        assert r.params.options == []

    def test_wrong_agent_literal(self):
        with pytest.raises(ValidationError):
            ClarificationNLUResult(
                type="clarification",
                intent="x",
                selected_agent="file_agent",  # wrong: must be communication_agent
                action="ask_clarification",
                params={"question": "?"},
                metadata={"reason": "r", "confidence_score": 0.2, "requires_user_approval": False},
            )


# ── DirectResponseNLUResult ───────────────────────────────────────────────────

class TestDirectResponseNLUResult:
    def test_valid(self):
        r = DirectResponseNLUResult(
            type="direct_response",
            intent="chitchat",
            params={"answer": "안녕하세요!"},
            metadata={"reason": "단순 인사", "confidence_score": 1.0, "requires_user_approval": False},
        )
        assert r.params["answer"] == "안녕하세요!"


# ── AGENT_TIMEOUT_MAP ─────────────────────────────────────────────────────────

class TestAgentTimeoutMap:
    def test_default_values(self):
        assert AGENT_TIMEOUT_MAP["archive_agent"] == 300
        assert AGENT_TIMEOUT_MAP["calendar_agent"] == 60

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("AGENT_TIMEOUT_OVERRIDES", "archive_agent:900,file_agent:180")
        result = _build_timeout_map()
        assert result["archive_agent"] == 900
        assert result["file_agent"] == 180
        assert result["calendar_agent"] == 60  # unchanged

    def test_env_override_invalid_value_ignored(self, monkeypatch):
        monkeypatch.setenv("AGENT_TIMEOUT_OVERRIDES", "archive_agent:notanumber")
        result = _build_timeout_map()
        assert result["archive_agent"] == 300  # unchanged

    def test_env_override_empty(self, monkeypatch):
        monkeypatch.setenv("AGENT_TIMEOUT_OVERRIDES", "")
        result = _build_timeout_map()
        assert result["archive_agent"] == 300


# ── NLU_CONFIDENCE_THRESHOLD ──────────────────────────────────────────────────

class TestConfidenceThreshold:
    def test_default(self):
        assert NLU_CONFIDENCE_THRESHOLD == 0.7

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NLU_CONFIDENCE_THRESHOLD", "0.8")
        from importlib import reload
        import agents.cassiopeia_agent.models as models_mod
        reload(models_mod)
        assert models_mod.NLU_CONFIDENCE_THRESHOLD == 0.8
        # 원복
        monkeypatch.delenv("NLU_CONFIDENCE_THRESHOLD", raising=False)
        reload(models_mod)
