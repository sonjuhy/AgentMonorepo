"""
에이전트 로컬 캐시 및 대용량 데이터 분산 저장을 위한 추상 인터페이스.
하이브리드 데이터 관리 아키텍처에 따라 각 에이전트는 이 인터페이스를 구현하여 
도메인 데이터를 자체 관리하고 오케스트라에는 reference_id만 전달합니다.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseStorageManager(ABC):
    """분산 저장소(로컬 DB, 파일 시스템, Vector DB 등)의 기본 인터페이스."""

    @abstractmethod
    async def save_data(self, data: Any, metadata: dict[str, Any] | None = None) -> str:
        """
        데이터를 저장소에 저장하고 고유한 참조 식별자(reference_id)를 반환합니다.

        Args:
            data: 저장할 본문 데이터 (대용량 텍스트, 딕셔너리, 바이너리 등).
            metadata: 데이터와 함께 저장할 추가 메타 정보.

        Returns:
            str: 저장된 데이터를 조회할 수 있는 고유 식별자 (예: URI, UUID 등).
        """
        pass

    @abstractmethod
    async def get_data(self, reference_id: str) -> Any | None:
        """
        주어진 참조 식별자(reference_id)에 해당하는 데이터를 조회합니다.

        Args:
            reference_id: 데이터를 조회할 고유 식별자.

        Returns:
            Any | None: 저장된 데이터. 존재하지 않을 경우 None 반환.
        """
        pass

    @abstractmethod
    async def delete_data(self, reference_id: str) -> bool:
        """
        주어진 참조 식별자(reference_id)에 해당하는 데이터를 삭제합니다.

        Args:
            reference_id: 삭제할 데이터의 고유 식별자.

        Returns:
            bool: 삭제 성공 시 True, 실패 또는 존재하지 않을 시 False 반환.
        """
        pass
