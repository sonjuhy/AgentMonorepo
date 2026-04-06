from datetime import datetime
from typing import Protocol, Any
from shared_core.messaging import AgentMessage
from shared_core.calendar.interfaces import CalendarEvent, CalendarEventId

class ScheduleAgentProtocol(Protocol):
    """
    구글 캘린더 기반 일정 관리 에이전트의 동작을 정의하는 인터페이스입니다.
    """

    async def list_schedules(self, start_time: datetime, end_time: datetime) -> list[CalendarEvent]:
        """
        특정 기간 동안의 일정을 가져옵니다.
        """
        ...

    async def add_schedule(self, event: CalendarEvent) -> CalendarEventId:
        """
        새로운 일정을 등록합니다.
        """
        ...

    async def modify_schedule(self, event_id: CalendarEventId, event: CalendarEvent) -> bool:
        """
        기존 일정을 수정합니다.
        """
        ...

    async def remove_schedule(self, event_id: CalendarEventId) -> bool:
        """
        일정을 삭제합니다.
        """
        ...

    async def process_message(self, message: AgentMessage) -> Any:
        """
        메시지 브로커를 통해 전달된 일정 관리 요청(create_event, list_events 등)을 처리합니다.
        """
        ...
