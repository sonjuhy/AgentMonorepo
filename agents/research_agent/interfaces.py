from pathlib import Path
from typing import Protocol, Any
from shared_core.messaging import AgentMessage

class ResearchAgentProtocol(Protocol):
    """
    웹 서핑 및 자료 조사를 자동화하는 리서치 에이전트의 인터페이스입니다.
    """

    async def conduct_research(self, topic: str) -> str:
        """
        특정 주제에 대해 웹 조사를 수행하고 요약 보고서를 작성합니다.

        Args:
            topic: 조사할 주제.

        Returns:
            요약된 조사 결과 보고서.
        """
        ...

    async def get_search_citations(self, topic: str) -> list[str]:
        """
        조사한 결과에 대한 출처 목록을 가져옵니다.

        Args:
            topic: 주제.

        Returns:
            출처 URL 리스트.
        """
        ...

    async def save_report(self, content: str, file_path: Path | str) -> bool:
        """
        조사 결과를 마크다운(.md) 파일로 저장합니다.

        Args:
            content: 저장할 마크다운 내용.
            file_path: 저장할 파일 경로 또는 파일명.

        Returns:
            저장 성공 여부.
        """
        ...

    async def process_message(self, message: AgentMessage) -> str:
        """
        메시지 브로커를 통해 전달된 조작 요청을 처리합니다.

        Args:
            message: AgentMessage (action="search_and_report" 등).

        Returns:
            작업 완료 결과 메시지.
        """
        ...
