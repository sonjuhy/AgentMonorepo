"""
Archive Agent 추상 인터페이스 (Protocol)
- python-strict-typing 전략: 엄격한 정적 타입 선언 및 추상 인터페이스
- ephemeral-docker-ops 전략: 단발성 실행 사이클 계약
- v2: ArchiveRedisListenerProtocol 추가 (Orchestra 연동 모드)
"""

from typing import Any, Protocol

from .models import ExecutionResult, ParsedTask, PlanningTaskResult, RawPayload


class ArchiveAgentProtocol(Protocol):
    """
    Archive Agent의 동작을 정의하는 추상 인터페이스입니다.
    이 에이전트는 무한 루프나 데몬 없이, 스케줄링된 1회 실행 주기를 갖습니다.
    (ephemeral 모드: cron 스케줄러 또는 직접 실행용)
    """

    agent_name: str

    async def fetch_pending_tasks(self) -> list[RawPayload]:
        """
        Notion 데이터베이스에서 기획 단계에 있는 작업 목록을 가져옵니다.
        요청 시 반드시 헤더에 "Notion-Version": "2022-06-28"를 포함해야 합니다.

        Returns:
            list[RawPayload]: 파싱되기 전의 Notion API JSON 리스트.
        """
        ...

    async def process_task(self, task_data: ParsedTask) -> ExecutionResult:
        """
        개별 작업에 대하여 아카이브 에이전트의 구체적 로직을 단발성으로 수행합니다.

        Args:
            task_data (ParsedTask): 파싱 완료된 작업 데이터.

        Returns:
            ExecutionResult: (성공 여부, 처리 결과 메시지)
        """
        ...

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점입니다.
        작업을 가져오고 파싱하여 처리한 후 곧바로 프로세스를 종료(자연 종료)해야 합니다.
        (ephemeral-docker-ops 전략 준수: while True 혹은 asyncio.sleep 반복 금지)
        """
        ...


class ArchiveRedisListenerProtocol(Protocol):
    """
    OrchestraManager Redis 큐 수신 모드 인터페이스.

    - Inbound:  BLPOP agent:archive_agent:tasks  (DispatchMessage 형식)
    - Outbound: HTTP POST {orchestra_url}/results  (AgentResult 형식)
    - Health:   Redis Hash agent:archive_agent:health  (15초 주기 heartbeat)

    FastAPI lifespan에서 asyncio.Task로 실행되는 백그라운드 루프입니다.
    """

    async def listen_tasks(self) -> None:
        """
        agent:archive_agent:tasks 큐를 BLPOP으로 감시하는 메인 루프.
        각 태스크를 handle_task()로 처리하며, CancelledError를 감지하여 정상 종료한다.
        """
        ...

    async def handle_task(self, raw: str) -> None:
        """
        Redis에서 수신한 JSON 문자열을 DispatchMessage로 파싱하고
        ArchiveAgent.handle_dispatch()에 위임한 뒤 결과를 보고한다.

        Args:
            raw: BLPOP으로 수신한 직렬화된 JSON 문자열.
        """
        ...

    async def _report_result(
        self,
        task_id: str,
        result_data: PlanningTaskResult,
        status: str,
        error: dict[str, Any] | None,
    ) -> None:
        """
        처리 결과를 OrchestraManager POST /results 엔드포인트로 전송한다.

        Args:
            task_id: 원본 DispatchMessage의 task_id.
            result_data: PlanningTaskResult 딕셔너리.
            status: "COMPLETED" | "FAILED".
            error: 실패 시 {code, message, traceback}, 성공 시 None.
        """
        ...

    async def _heartbeat_loop(self) -> None:
        """
        15초 주기로 agent:archive_agent:health Redis Hash를 갱신한다.
        OrchestraManager의 HealthMonitor가 이 값을 읽어 가용 여부를 판단한다.
        """
        ...
