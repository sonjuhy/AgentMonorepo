from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict

type SearchProviderName = Literal["gemini", "perplexity"]
type Citations = list[str]

class SearchResult(BaseModel):
    """
    웹 서치 결과 데이터를 담는 모델입니다.
    """
    model_config = ConfigDict(frozen=True)

    answer: str
    citations: Citations = []
    metadata: dict[str, Any] | None = None

class SearchProviderProtocol(Protocol):
    """
    웹 검색 엔진(Gemini Search, Perplexity 등)과의 통신을 위한 인터페이스입니다.
    """

    async def search(self, query: str) -> SearchResult:
        """
        주어진 쿼리에 대해 웹 서치를 수행하고 구조화된 결과를 반환합니다.

        Args:
            query: 검색할 질문이나 키워드.

        Returns:
            SearchResult: 검색 결과 텍스트와 출처(Citation) 정보.
        """
        ...

    async def search_with_context(self, query: str, context: str) -> SearchResult:
        """
        추가 컨텍스트를 포함하여 좀 더 정밀한 조사를 수행합니다.

        Args:
            query: 검색할 질문.
            context: 조사의 배경이 되는 추가 정보.

        Returns:
            SearchResult: 컨텍스트가 반영된 검색 결과.
        """
        ...
