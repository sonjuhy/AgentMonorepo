from datetime import datetime
from typing import Any, Protocol
from pydantic import BaseModel, ConfigDict

class LLMUsage(BaseModel):
    """
    LLM 사용량 통계 정보입니다.
    """
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class LLMLogEntry(BaseModel):
    """
    LLM 요청 및 응답 로그 엔트리입니다.
    """
    model_config = ConfigDict(frozen=True)

    request_id: str
    model_name: str
    prompt: str
    response: str
    usage: LLMUsage
    timestamp: datetime = datetime.now()
    metadata: dict[str, Any] | None = None

class LLMProviderProtocol(Protocol):
    """
    LLM 엔진(Gemini 등)과의 통신을 위한 인터페이스입니다.
    """

    async def generate_response(
        self, 
        prompt: str, 
        system_instruction: str | None = None
    ) -> tuple[str, LLMUsage]:
        """
        프롬프트를 전송하고 응답과 사용량을 반환합니다.
        
        Args:
            prompt: 사용자 프롬프트.
            system_instruction: 시스템 지침.
            
        Returns:
            응답 텍스트와 토큰 사용량 정보의 튜플.
        """
        ...

class LLMLoggerProtocol(Protocol):
    """
    LLM 로그를 기록하고 관리하는 인터페이스입니다.
    """

    async def log(self, entry: LLMLogEntry) -> None:
        """로그를 저장소에 기록합니다."""
        ...
