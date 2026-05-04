"""
에이전트 레지스트리 구현체
- AgentRegistryProtocol 구현
- 등록된 에이전트의 이름과 역할 설명을 관리 (LLM 컨텍스트 제공용)
"""

from shared_core.messaging import AgentName

from .interfaces import AgentRegistryProtocol

# 기본 등록 에이전트: 이름 → 역할 설명
_DEFAULT_AGENTS: dict[AgentName, str] = {
    "planning": "소프트웨어 기획, 요구사항 분석, 설계 문서 작성, 태스크 분해 요청을 처리합니다. Notion 데이터베이스를 조회하고 업데이트합니다.",
    "slack": "Slack 알림 발송, 메시지 전달, 승인 대기 태스크 알림 등 커뮤니케이션 요청을 처리합니다.",
    "file": "파일 생성, 읽기, 수정, 삭제 등 로컬 파일 시스템 작업을 처리합니다.",
}


class AgentRegistry:
    """
    AgentRegistryProtocol의 구체 구현체.
    에이전트 이름과 역할 설명을 인메모리 딕셔너리로 관리합니다.
    """

    def __init__(self, include_defaults: bool = True) -> None:
        self._agents: dict[AgentName, str] = {}
        if include_defaults:
            for name, desc in _DEFAULT_AGENTS.items():
                self._agents[name] = desc

    def register_agent(self, name: AgentName, capability_description: str) -> None:
        """에이전트를 레지스트리에 추가합니다."""
        self._agents[name] = capability_description
        print(f"[registry] 에이전트 등록: {name}")

    def unregister_agent(self, name: AgentName) -> None:
        """에이전트를 레지스트리에서 제거합니다."""
        if name in self._agents:
            del self._agents[name]
            print(f"[registry] 에이전트 해제: {name}")

    def get_agent_capabilities(self) -> dict[AgentName, str]:
        """등록된 모든 에이전트의 능력 정보를 반환합니다 (LLM 컨텍스트용)."""
        return dict(self._agents)
