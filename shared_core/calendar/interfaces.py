from datetime import datetime
from typing import Any, Protocol, Literal
from pydantic import BaseModel, ConfigDict

type CalendarEventId = str
type EventStatus = Literal["confirmed", "tentative", "cancelled"]

class CalendarEvent(BaseModel):
    """
    일정 정보를 담는 데이터 모델입니다. (구글 캘린더 규격 기반)
    """
    model_config = ConfigDict(frozen=True)

    event_id: CalendarEventId | None = None
    title: str
    start_time: datetime
    end_time: datetime
    description: str | None = None
    location: str | None = None
    attendees: list[str] = []
    status: EventStatus = "confirmed"

class CalendarProviderProtocol(Protocol):
    """
    구글 캘린더 등 캘린더 서비스와의 연동을 위한 인터페이스입니다.
    """

    async def get_events(self, start_min: datetime, start_max: datetime) -> list[CalendarEvent]:
        """
        주어진 시간 범위 내의 일정 목록을 조회합니다.
        """
        ...

    async def create_event(self, event: CalendarEvent) -> CalendarEventId:
        """
        새로운 일정을 생성합니다.
        """
        ...

    async def update_event(self, event_id: CalendarEventId, event: CalendarEvent) -> bool:
        """
        기존 일정을 수정합니다.
        """
        ...

    async def delete_event(self, event_id: CalendarEventId) -> bool:
        """
        일정을 삭제합니다.
        """
        ...
