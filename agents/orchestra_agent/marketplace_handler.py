"""
MarketplaceHandler — 외부 마켓플레이스 에이전트 설치 관리자
- 외부 URL/ID로부터 에이전트 명세(Manifest)를 가져옵니다.
- AgentBuilderHandler를 사용하여 에이전트를 빌드합니다.
- 빌드 완료 후 AgentRegistry(인메모리)와 HealthMonitor(Redis)에 에이전트를 등록합니다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from .agent_builder_handler import AgentBuilderHandler
from .registry import AgentRegistry

if TYPE_CHECKING:
    from .health_monitor import HealthMonitor

logger = logging.getLogger("orchestra_agent.marketplace_handler")


class MarketplaceHandler:
    def __init__(
        self,
        builder_handler: AgentBuilderHandler,
        registry: AgentRegistry,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        self.builder = builder_handler
        self.registry = registry
        self.health_monitor = health_monitor

    async def install_from_marketplace(self, item_url: str, task_id: str) -> dict[str, Any]:
        """
        외부 마켓플레이스 URL에서 에이전트 정보를 가져와 설치 및 등록합니다.

        매니페스트 필수/선택 필드:
          name         (str, 필수)   — 에이전트 이름 (예: "weather")
          code         (str, 필수)   — user_code.py 소스 문자열
          language     (str)         — "python" | "javascript" (기본값: "python")
          description  (str)         — 에이전트 설명
          packages     (list[str])   — 설치할 패키지 목록
          port         (int)         — FastAPI 서버 포트 (기본값: 8010)
          permissions  (str)         — "minimal" | "standard" | "trusted" (기본값: "standard")
          lifecycle_type (str)       — "long_running" | "ephemeral" (기본값: "long_running")
          capabilities (list[str])   — NLU 라우팅용 액션 목록
          nlu_description (str)      — NLU 동적 캐퍼빌리티 설명 (동적 라우팅용)
        """
        logger.info("[Marketplace] 설치 시도: %s", item_url)

        try:
            # 1. 마켓플레이스로부터 매니페스트(명세) 가져오기
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(item_url)
                resp.raise_for_status()
                manifest: dict[str, Any] = resp.json()

            agent_name = manifest.get("name", "").strip()
            if not agent_name:
                raise ValueError("매니페스트에 에이전트 이름(name)이 누락되었습니다.")

            if not manifest.get("code", "").strip():
                raise ValueError("매니페스트에 실행 코드(code)가 누락되었습니다.")

            # 2. 에이전트 빌드 실행
            build_result = await self.builder.build_agent(manifest, task_id)

            if build_result.get("status") == "FAILED":
                return build_result

            # 3. 레지스트리 등록 — 인메모리(AgentRegistry) + Redis(HealthMonitor)
            registered_name = f"{agent_name}_agent"
            capability_desc = manifest.get("description", f"{agent_name} 에이전트")
            capabilities: list[str] = manifest.get("capabilities") or []
            lifecycle_type: str = manifest.get("lifecycle_type", "long_running")
            nlu_description: str = manifest.get("nlu_description", "")

            self.registry.register_agent(registered_name, capability_desc)

            if self.health_monitor is not None:
                await self.health_monitor.register_agent(
                    registered_name,
                    capabilities,
                    lifecycle_type=lifecycle_type,
                    nlu_description=nlu_description,
                )

            logger.info("[Marketplace] 설치 및 등록 성공: %s", registered_name)

            return {
                "status": "COMPLETED",
                "task_id": task_id,
                "result_data": {
                    "summary": f"마켓플레이스로부터 '{registered_name}' 에이전트 설치 및 등록이 완료되었습니다.",
                    "details": build_result.get("result_data"),
                },
            }

        except Exception as exc:
            logger.error("[Marketplace] 설치 중 오류 발생: %s", exc)
            return {
                "status": "FAILED",
                "task_id": task_id,
                "result_data": {},
                "error": {"code": "MARKETPLACE_INSTALL_ERROR", "message": str(exc), "traceback": None},
                "usage_stats": {},
            }
