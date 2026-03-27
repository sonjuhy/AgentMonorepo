from typing import Protocol, Any
from shared_core.messaging import AgentMessage, AgentName

class OrchestraAgentProtocol(Protocol):
    """
    모든 에이전트를 조율하는 Orchestra 에이전트의 인터페이스입니다.
    """

    async def analyze_user_intent(self, user_input: str) -> list[AgentMessage]:
        """
        LLM을 사용하여 사용자의 의도를 분석하고 필요한 에이전트 메시지 목록을 생성합니다.
        
        Args:
            user_input: 사용자의 자연어 입력.
            
        Returns:
            각 에이전트에게 전송할 표준 메시지 리스트.
        """
        ...

    async def handle_agent_response(self, response_message: AgentMessage) -> Any:
        """
        하위 에이전트로부터 받은 결과를 처리하고 사용자에게 전달할 최종 응답을 구성합니다.
        
        Args:
            response_message: 에이전트가 반환한 결과 메시지.
        """
        ...

class AgentRegistryProtocol(Protocol):
    """
    관리 대상 에이전트들을 동적으로 등록하고 관리하는 인터페이스입니다.
    """

    def register_agent(self, name: AgentName, capability_description: str) -> None:
        """에이전트를 레지스트리에 추가합니다."""
        ...

    def unregister_agent(self, name: AgentName) -> None:
        """에이전트를 레지스트리에서 제거합니다."""
        ...

    def get_agent_capabilities(self) -> dict[AgentName, str]:
        """등록된 모든 에이전트의 능력 정보를 반환합니다 (LLM 컨텍스트용)."""
        ...
