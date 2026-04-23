"""
OrchestraAgent 구체 구현체
- OrchestraAgentProtocol 구현
- Redis Pub/Sub 기반 장기 실행(long-running) 서비스
- 사용자 요청 수신 → LLM 의도 분석 → 하위 에이전트 디스패치 → 응답 집계
"""

import asyncio
import os
from typing import Any

from shared_core.messaging import AgentMessage, AgentName, RedisMessageBroker

from .intent_analyzer import ClaudeAPIIntentAnalyzer, IntentAnalyzerProtocol
from .registry import AgentRegistry

_AGENT_NAME: AgentName = "orchestra"

_RESPONSE_TIMEOUT_SEC: float = float(os.environ.get("RESPONSE_TIMEOUT_SEC", "30.0"))


class OrchestraAgent:
    """
    OrchestraAgentProtocol의 구체 구현체.

    역할:
    - `agent:orchestra` Redis 채널을 구독하여 메시지를 수신합니다.
    - action=`user_request`: 사용자 입력을 LLM으로 분석하고 하위 에이전트에 배분합니다.
    - action=`agent_response`: 하위 에이전트로부터 받은 결과를 처리·집계합니다.

    환경 변수:
        ANTHROPIC_API_KEY : Claude API 인증 키
        REDIS_URL         : Redis 서버 URL (기본값: redis://localhost:6379)
    """

    agent_name: str = "orchestra-agent"

    def __init__(
        self,
        broker: RedisMessageBroker,
        registry: AgentRegistry | None = None,
        intent_analyzer: IntentAnalyzerProtocol | None = None,
    ) -> None:
        self._broker = broker
        self._registry = registry or AgentRegistry()
        self._intent_analyzer = intent_analyzer or ClaudeAPIIntentAnalyzer()

        # correlation_id → (완료 Future, 응답 목록)
        self._pending: dict[str, tuple[asyncio.Future[None], list[AgentMessage]]] = {}

    # ------------------------------------------------------------------
    # OrchestraAgentProtocol 구현
    # ------------------------------------------------------------------

    async def analyze_user_intent(self, user_input: str) -> list[AgentMessage]:
        """
        LLM을 사용하여 사용자의 의도를 분석하고 필요한 에이전트 메시지 목록을 생성합니다.

        Args:
            user_input: 사용자의 자연어 입력.

        Returns:
            각 에이전트에게 전송할 표준 메시지 리스트.
        """
        capabilities = self._registry.get_agent_capabilities()
        messages = await self._intent_analyzer.analyze(user_input, capabilities)
        print(f"[{self.agent_name}] 의도 분석 완료: {[m.receiver for m in messages]}")
        return messages

    async def handle_agent_response(self, response_message: AgentMessage) -> Any:
        """
        하위 에이전트로부터 받은 결과를 처리하고 사용자에게 전달할 최종 응답을 구성합니다.

        Args:
            response_message: 에이전트가 반환한 결과 메시지.

        Returns:
            집계된 응답 데이터 (payload dict).
        """
        correlation_id: str | None = response_message.payload.get("correlation_id")
        print(
            f"[{self.agent_name}] 응답 수신: {response_message.sender} "
            f"action={response_message.action}"
        )

        if correlation_id and correlation_id in self._pending:
            future, responses = self._pending[correlation_id]
            responses.append(response_message)

            # 완료 신호가 포함된 경우 Future를 resolve
            if response_message.payload.get("done"):
                if not future.done():
                    future.set_result(None)

        return response_message.payload

    # ------------------------------------------------------------------
    # 내부 디스패치 로직
    # ------------------------------------------------------------------

    async def _dispatch_messages(
        self,
        messages: list[AgentMessage],
        correlation_id: str,
    ) -> list[bool]:
        """각 에이전트 메시지를 Redis 채널에 발행합니다."""
        results: list[bool] = []
        for msg in messages:
            # correlation_id를 payload에 주입하여 응답 추적 가능하게 함
            enriched = AgentMessage(
                sender=msg.sender,
                receiver=msg.receiver,
                action=msg.action,
                payload={**msg.payload, "correlation_id": correlation_id},
            )
            success = await self._broker.publish(enriched)
            results.append(success)
            status = "발행 성공" if success else "발행 실패"
            print(f"[{self.agent_name}] → {msg.receiver} ({msg.action}): {status}")
        return results

    async def _handle_user_request(self, message: AgentMessage) -> None:
        """action=user_request 메시지를 처리합니다."""
        user_input: str = message.payload.get("text", "")
        if not user_input:
            print(f"[{self.agent_name}] 빈 user_request 무시")
            return

        # 의도 분석
        agent_messages = await self.analyze_user_intent(user_input)

        # 상관 ID 생성 (타임스탬프 기반)
        correlation_id = f"{message.payload.get('ts', '')}_{message.timestamp.timestamp()}"

        # 응답 추적용 Future 등록
        future: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        self._pending[correlation_id] = (future, [])

        # 디스패치
        await self._dispatch_messages(agent_messages, correlation_id)

        # 응답 대기 (타임아웃 허용 – 에이전트가 응답 안 할 수도 있음)
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=_RESPONSE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            print(f"[{self.agent_name}] 응답 대기 타임아웃 (correlation_id={correlation_id})")
        finally:
            self._pending.pop(correlation_id, None)

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        에이전트 장기 실행 루프.
        `agent:orchestra` 채널을 구독하여 메시지를 처리합니다.
        """
        print(f"[{self.agent_name}] 시작 – agent:orchestra 채널 구독 중")

        async for message in self._broker.subscribe(_AGENT_NAME):
            print(
                f"[{self.agent_name}] 메시지 수신: "
                f"from={message.sender} action={message.action}"
            )

            if message.action == "user_request":
                asyncio.create_task(self._handle_user_request(message))

            elif message.action == "agent_response":
                await self.handle_agent_response(message)

            else:
                print(f"[{self.agent_name}] 알 수 없는 action 무시: {message.action}")
