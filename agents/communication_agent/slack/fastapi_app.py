"""
FastAPI 서버 + Slack SDK Socket Mode 실시간 리스너 (v3)
- slack_bolt AsyncApp + AsyncSocketModeHandler 를 FastAPI lifespan 백그라운드 태스크로 실행
- slack_sdk AsyncWebClient 로 메시지 전송 (Incoming Webhook 대체)
- Server-Sent Events(SSE) 를 통한 실시간 메시지 스트리밍 지원
- GET /messages/history  : Slack conversations.history API 채널 메시지 조회
- GET /messages/recent   : 서버가 수신한 인메모리 최근 메시지 조회
- GET /messages/live     : SSE 실시간 수신 메시지 스트리밍
- POST /send             : 채널 메시지 전송
- POST /notify           : Notion 승인 대기 태스크 알림
- GET /health            : 헬스체크
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from ..models import SlackEvent
from .llm_classifier import ClassifierProtocol
from .dispatcher import DockerDispatcher

logger = logging.getLogger("slack_agent.fastapi_app")

# uvicorn 으로 직접 실행 시에도 로그가 출력되도록 루트 로거 핸들러 보장
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# 인메모리 최근 메시지 최대 보관 수
_MAX_RECENT_MESSAGES = 100


# ─── 싱글톤 컨텍스트 ────────────────────────────────────────────────────────────

class _AppContext:
    """FastAPI 앱 생애 동안 단일 인스턴스로 유지되는 공유 상태."""

    def __init__(self) -> None:
        self.web_client: AsyncWebClient | None = None
        self.socket_handler: AsyncSocketModeHandler | None = None
        self.classifier: ClassifierProtocol | None = None
        self.dispatcher: DockerDispatcher | None = None
        self._socket_task: asyncio.Task | None = None  # type: ignore[type-arg]

        # ── 수신 메시지 저장소 ──
        # 최근 N개 메시지를 deque 로 인메모리 보관
        self.recent_messages: deque[dict[str, Any]] = deque(maxlen=_MAX_RECENT_MESSAGES)
        # SSE 구독자 큐 목록 (클라이언트마다 별도 asyncio.Queue)
        self.sse_queues: list[asyncio.Queue[dict[str, Any]]] = []


_ctx = _AppContext()


# ─── 수신 메시지 내부 저장 ──────────────────────────────────────────────────────

def _store_received_message(event: dict[str, Any]) -> dict[str, Any]:
    """
    수신된 Slack 이벤트를 인메모리(recent_messages)에 저장하고
    모든 SSE 구독자 큐에 브로드캐스트합니다.

    Args:
        event (dict[str, Any]): Slack 이벤트 딕셔너리.

    Returns:
        dict[str, Any]: 저장된 메시지 레코드.
    """
    record: dict[str, Any] = {
        "user": event.get("user", ""),
        "channel": event.get("channel", ""),
        "text": event.get("text", ""),
        "ts": event.get("ts", ""),
        "thread_ts": event.get("thread_ts"),
        "received_at": time.time(),
    }
    _ctx.recent_messages.append(record)

    # SSE 구독자 전체에 브로드캐스트 (Non-blocking)
    for q in list(_ctx.sse_queues):
        try:
            q.put_nowait(record)
        except asyncio.QueueFull:
            pass  # 느린 클라이언트는 메시지 누락 허용

    return record


# ─── Slack 이벤트 파싱 ──────────────────────────────────────────────────────────

def _parse_slack_event(event: dict[str, Any]) -> SlackEvent | None:
    """
    slack_bolt 이벤트 핸들러의 event 객체를 SlackEvent TypedDict로 변환합니다.

    Args:
        event (dict[str, Any]): slack_bolt handle_message 의 event 딕셔너리.

    Returns:
        SlackEvent | None: 변환 성공 시 SlackEvent, 무시해야 할 이벤트는 None.
    """
    if event.get("subtype") or event.get("bot_id"):
        return None

    text: str = event.get("text", "").strip()
    if not text:
        return None

    return SlackEvent(
        user=event.get("user", ""),
        channel=event.get("channel", ""),
        text=text,
        ts=event.get("ts", ""),
        thread_ts=event.get("thread_ts"),
    )


# ─── LLM 분류기 팩토리 ──────────────────────────────────────────────────────────

def _build_classifier(backend: str) -> ClassifierProtocol:
    """
    환경변수 CLASSIFIER_BACKEND 값에 따라 적합한 LLM 분류기를 반환합니다.

    Args:
        backend (str): 백엔드 식별자 claude_api | gemini_api | claude_cli | gemini_cli.

    Returns:
        ClassifierProtocol: 선택된 분류기 인스턴스.
    """
    b = backend.lower()
    if b == "gemini_api":
        from .llm_classifier import GeminiAPIClassifier
        return GeminiAPIClassifier()
    if b == "claude_cli":
        from .llm_classifier import ClaudeCLIClassifier
        return ClaudeCLIClassifier()
    if b == "gemini_cli":
        from .llm_classifier import GeminiCLIClassifier
        return GeminiCLIClassifier()
    from .llm_classifier import ClaudeAPIClassifier
    return ClaudeAPIClassifier()


# ─── FastAPI lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 앱의 시작/종료 시 slack_bolt Socket Mode 핸들러를 관리합니다.
    AsyncSocketModeHandler 를 asyncio 백그라운드 태스크로 실행합니다.

    Yields:
        None: 앱이 요청을 처리하는 동안 컨텍스트를 유지합니다.
    """
    bot_token: str = os.environ["SLACK_BOT_TOKEN"]
    app_token: str = os.environ["SLACK_APP_TOKEN"]
    backend: str = os.environ.get("CLASSIFIER_BACKEND", "gemini_api")

    # ── 컨텍스트 초기화 ──
    _ctx.web_client = AsyncWebClient(token=bot_token)
    _ctx.classifier = _build_classifier(backend)
    _ctx.dispatcher = DockerDispatcher()

    # ── slack_bolt AsyncApp 생성 및 이벤트 핸들러 등록 ──
    bolt_app = AsyncApp(token=bot_token)

    @bolt_app.event("message")
    async def handle_message(event: dict, say: Any) -> None:  # type: ignore[type-arg]
        """
        Slack 채널 메시지 이벤트를 수신합니다.
        - 인메모리 저장 및 SSE 브로드캐스트
        - LLM 분류 후 에이전트 컨테이너에 디스패치
        - 처리 결과를 스레드로 응답

        Args:
            event (dict): slack_bolt 에서 전달된 이벤트 데이터.
            say (Any): 현재 채널/스레드에 메시지를 보내는 slack_bolt 유틸리티.
        """
        # ① 수신 즉시 저장 및 SSE 브로드캐스트 (봇/서브타입 제외)
        if not event.get("subtype") and not event.get("bot_id"):
            _store_received_message(event)

        slack_event = _parse_slack_event(event)
        if slack_event is None:
            return

        # ───── 수신 메시지 콘솔 출력 ─────
        print("\n" + "=" * 60)
        print(f"  [SLACK 수신] 새 메시지")
        print(f"  user    : {slack_event['user']}")
        print(f"  channel : {slack_event['channel']}")
        print(f"  ts      : {slack_event['ts']}")
        print(f"  text    : {slack_event['text'][:120]}")
        print("=" * 60)
        logger.info(
            "[bolt] 메시지 수신 — user=%s channel=%s: %s",
            slack_event["user"],
            slack_event["channel"],
            slack_event["text"][:80],
        )

        # ② LLM 분류
        print(f"  [분류 중] LLM 에이전트 라우팅 시작...")
        try:
            agent_name = await _ctx.classifier.classify(slack_event)  # type: ignore[union-attr]
            print(f"  [분류 완료] → {agent_name}")
            logger.info("[bolt] 분류 결과: %s", agent_name)
        except Exception as exc:
            print(f"  [분류 실패] {exc}")
            logger.exception("[bolt] 분류 실패: %s", exc)
            await say(
                text=f"에이전트 분류 중 오류가 발생했습니다: {exc}",
                thread_ts=slack_event["ts"],
            )
            return

        # ③ 에이전트 컨테이너 디스패치
        print(f"  [디스패치 중] {agent_name} 컨테이너 실행 요청...")
        success, message = await _ctx.dispatcher.dispatch(agent_name, slack_event)  # type: ignore[union-attr]
        status_label = "완료" if success else "실패"
        print(f"  [디스패치 {status_label}] {message}")
        print("" + "-" * 60 + "\n")
        logger.info("[bolt] 디스패치 %s: %s", status_label, message)

        # ④ Slack 스레드 응답
        status_emoji = "✅" if success else "❌"
        await say(
            text=f"{status_emoji} *{agent_name}* 에이전트에 전달했습니다.\n`{message}`",
            thread_ts=slack_event["ts"],
        )

    @bolt_app.error
    async def handle_error(error: Exception) -> None:
        """slack_bolt 앱 레벨 에러 핸들러."""
        print(f"\n[bolt ERROR] {error}")
        logger.error("[bolt] 앱 에러: %s", error)

    # ── AsyncSocketModeHandler 를 백그라운드 태스크로 실행 ──
    handler = AsyncSocketModeHandler(bolt_app, app_token=app_token)
    _ctx.socket_handler = handler

    async def _run_socket() -> None:
        """Socket Mode 핸들러를 백그라운드에서 실행하는 코루틴."""
        logger.info("[lifespan] Slack Socket Mode 연결 시작 (backend=%s)", backend)
        await handler.start_async()

    _ctx._socket_task = asyncio.create_task(_run_socket())

    yield  # 서버가 요청을 처리하는 동안 대기

    # ── 종료 시 정리 ──
    logger.info("[lifespan] Slack Socket Mode 종료 중...")
    # SSE 구독자 큐에 종료 신호 전송
    for q in list(_ctx.sse_queues):
        try:
            q.put_nowait({"event": "close"})
        except asyncio.QueueFull:
            pass

    if _ctx._socket_task and not _ctx._socket_task.done():
        _ctx._socket_task.cancel()
        try:
            await _ctx._socket_task
        except asyncio.CancelledError:
            pass
    await handler.close_async()
    logger.info("[lifespan] Slack Socket Mode 연결 종료 완료")


# ─── FastAPI 앱 정의 ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Slack Agent API",
    description="slack_bolt Socket Mode 기반 실시간 Slack 대화 에이전트 & REST API",
    version="3.0.0",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────────────────────────────
# 메시지 수신 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────────

@app.get("/messages/history", summary="Slack 채널 메시지 히스토리 조회")
async def get_channel_history(
    channel: str = Query(..., description="Slack 채널 ID (예: C06XXXXXXX)"),
    limit: int = Query(20, ge=1, le=200, description="조회할 메시지 수 (최대 200)"),
    oldest: str | None = Query(None, description="이 ts 이후 메시지만 조회"),
    latest: str | None = Query(None, description="이 ts 이전 메시지만 조회"),
) -> JSONResponse:
    """
    Slack conversations.history API를 통해 채널의 메시지 목록을 조회합니다.

    Query Parameters:
        channel (str): 조회할 Slack 채널 ID
        limit (int): 반환할 최대 메시지 수 (기본 20, 최대 200)
        oldest (str | None): 특정 ts 이후 메시지만 필터링
        latest (str | None): 특정 ts 이전 메시지만 필터링

    Returns:
        JSONResponse: {"ok": bool, "messages": list, "has_more": bool}
    """
    if _ctx.web_client is None:
        raise HTTPException(status_code=503, detail="WebClient가 초기화되지 않았습니다.")

    try:
        kwargs: dict[str, Any] = {"channel": channel, "limit": limit}
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest

        response = await _ctx.web_client.conversations_history(**kwargs)

        messages: list[dict[str, Any]] = response.get("messages", [])
        # 각 메시지에서 필요한 필드만 추출하여 반환
        parsed: list[dict[str, Any]] = [
            {
                "user": msg.get("user", msg.get("bot_id", "")),
                "text": msg.get("text", ""),
                "ts": msg.get("ts", ""),
                "thread_ts": msg.get("thread_ts"),
                "reply_count": msg.get("reply_count", 0),
                "is_bot": "bot_id" in msg,
            }
            for msg in messages
        ]

        return JSONResponse({
            "ok": True,
            "channel": channel,
            "messages": parsed,
            "has_more": response.get("has_more", False),
        })

    except Exception as exc:
        err_str = str(exc)
        # Slack API missing_scope 에러 → 500 대신 명확한 403 반환
        if "missing_scope" in err_str:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "missing_scope",
                    "message": "Slack 앱에 channels:history 스코프가 없습니다. Slack 앱 설정에서 Bot Token Scopes에 추가 후 앱을 재설치하세요.",
                    "needed_scopes": ["channels:history", "groups:history", "mpim:history", "im:history"],
                    "how_to_fix": "https://api.slack.com/apps → OAuth & Permissions → Bot Token Scopes → Add channels:history",
                },
            ) from exc
        logger.exception("[/messages/history] 조회 실패: %s", exc)
        raise HTTPException(status_code=500, detail=err_str) from exc


@app.get("/messages/recent", summary="서버 수신 메시지 인메모리 조회")
async def get_recent_messages(
    limit: int = Query(20, ge=1, le=_MAX_RECENT_MESSAGES, description="반환할 최근 메시지 수"),
    channel: str | None = Query(None, description="특정 채널 ID로 필터링"),
) -> JSONResponse:
    """
    Socket Mode를 통해 서버가 실시간으로 수신하여 인메모리에 저장한 최근 메시지를 반환합니다.

    Query Parameters:
        limit (int): 반환할 최근 메시지 수 (기본 20)
        channel (str | None): 특정 채널 ID 필터

    Returns:
        JSONResponse: {"ok": bool, "messages": list, "total_stored": int}
    """
    all_messages = list(_ctx.recent_messages)

    if channel:
        all_messages = [m for m in all_messages if m.get("channel") == channel]

    # 최신 순으로 정렬 후 limit 적용
    sorted_messages = sorted(all_messages, key=lambda m: m.get("ts", ""), reverse=True)
    result = sorted_messages[:limit]

    return JSONResponse({
        "ok": True,
        "messages": result,
        "total_stored": len(all_messages),
    })


@app.get("/messages/live", summary="실시간 메시지 스트리밍 (Server-Sent Events)")
async def stream_live_messages(
    channel: str | None = Query(None, description="특정 채널 ID로 필터링"),
) -> StreamingResponse:
    """
    Server-Sent Events(SSE) 를 통해 Socket Mode로 수신된 메시지를 실시간으로 스트리밍합니다.
    클라이언트가 연결을 끊을 때까지 메시지를 지속적으로 전송합니다.

    Query Parameters:
        channel (str | None): 특정 채널의 메시지만 수신할 경우 채널 ID 지정

    Returns:
        StreamingResponse: text/event-stream 형식의 SSE 스트림
    """
    # 각 SSE 클라이언트마다 독립적인 큐 생성 (최대 50개 메시지 버퍼)
    client_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
    _ctx.sse_queues.append(client_queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        """
        SSE 이벤트 스트림 제너레이터.
        클라이언트 연결 시 연결 확인 메시지를 전송하고
        이후 수신 메시지를 실시간으로 전달합니다.

        Yields:
            str: SSE 형식의 이벤트 문자열.
        """
        try:
            # 연결 성공 알림
            connect_data = json.dumps({
                "event": "connected",
                "message": "Slack 실시간 메시지 스트림 연결됨",
                "filter_channel": channel,
                "timestamp": time.time(),
            }, ensure_ascii=False)
            yield f"data: {connect_data}\n\n"

            while True:
                try:
                    # 30초마다 keepalive 핑 전송
                    record = await asyncio.wait_for(client_queue.get(), timeout=30.0)

                    # 서버 종료 신호
                    if record.get("event") == "close":
                        yield "data: {\"event\": \"server_closing\"}\n\n"
                        break

                    # 채널 필터 적용
                    if channel and record.get("channel") != channel:
                        continue

                    payload = json.dumps(record, ensure_ascii=False)
                    yield f"data: {payload}\n\n"

                except asyncio.TimeoutError:
                    # 30초 keepalive 핑
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            logger.info("[SSE] 클라이언트 연결 종료")
        finally:
            # 구독자 목록에서 제거
            if client_queue in _ctx.sse_queues:
                _ctx.sse_queues.remove(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 버퍼링 비활성화
        },
    )


# ──────────────────────────────────────────────────────────────────────────────────
# 메시지 전송 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────────

@app.post("/send", summary="Slack 채널에 메시지 전송")
async def send_message(request: Request) -> JSONResponse:
    """
    REST API를 통해 특정 Slack 채널에 메시지를 직접 전송합니다.

    Request Body (JSON):
        channel (str): Slack 채널 ID (예: "C06XXXXXXX")
        text (str): 전송할 메시지 텍스트
        thread_ts (str | None): 스레드 답글로 보낼 경우 원본 메시지의 ts

    Returns:
        JSONResponse: {"ok": bool, "ts": str | None}
    """
    if _ctx.web_client is None:
        raise HTTPException(status_code=503, detail="WebClient가 초기화되지 않았습니다.")

    body: dict[str, Any] = await request.json()
    channel: str = body.get("channel", "")
    text: str = body.get("text", "")
    thread_ts: str | None = body.get("thread_ts")

    if not channel or not text:
        raise HTTPException(status_code=400, detail="channel과 text는 필수입니다.")

    try:
        kwargs: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = await _ctx.web_client.chat_postMessage(**kwargs)
        return JSONResponse({"ok": True, "ts": response.get("ts")})
    except Exception as exc:
        logger.exception("[/send] Slack 메시지 전송 실패: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/notify", summary="Notion 승인 대기 태스크 Slack 알림 발송")
async def notify_pending_tasks() -> JSONResponse:
    """
    Notion 데이터베이스에서 '승인 대기중' 태스크를 조회하여 Slack으로 알림을 발송합니다.

    Returns:
        JSONResponse: {"ok": bool, "sent": int, "failed": int}
    """
    from .agent import SlackAgent
    from .notion_parser import parse_notion_task

    agent = SlackAgent(web_client=_ctx.web_client)
    sent = 0
    failed = 0

    raw_payloads = await agent.fetch_notifications()
    for raw in raw_payloads:
        task = parse_notion_task(raw)
        if task is None:
            failed += 1
            continue
        message = await agent.format_slack_message(task)
        success, msg = await agent.push_to_slack(message)
        if success:
            sent += 1
        else:
            failed += 1
            logger.warning("[/notify] 전송 실패 [%s]: %s", task["title"], msg)

    return JSONResponse({"ok": True, "sent": sent, "failed": failed})


# ──────────────────────────────────────────────────────────────────────────────────
# 유틸리티 엔드포인트
# ──────────────────────────────────────────────────────────────────────────────────

@app.get("/health", summary="헬스체크")
async def health_check() -> JSONResponse:
    """
    서비스 상태 및 Slack Socket Mode 연결 여부를 반환합니다.

    Returns:
        JSONResponse: {"status": "ok", "socket_running": bool, "sse_clients": int, "recent_messages": int}
    """
    is_running: bool = (
        _ctx._socket_task is not None
        and not _ctx._socket_task.done()
    )
    return JSONResponse({
        "status": "ok",
        "socket_running": is_running,
        "sse_clients": len(_ctx.sse_queues),
        "recent_messages_buffered": len(_ctx.recent_messages),
    })
