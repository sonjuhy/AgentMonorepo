import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScheduleAgentConfig:
    """
    일정 관리 에이전트의 설정 정보를 관리합니다.

    Attributes:
        calendar_id: 대상 구글 캘린더 ID. 기본값 "primary".
        service_account_key_file: 서비스 계정 JSON 키 파일 경로.
        service_account_key_json: 서비스 계정 JSON 키 문자열 (파일 대신 직접 주입 시 사용).
        scopes: 요청할 OAuth 스코프 목록.
    """

    calendar_id: str = "primary"
    service_account_key_file: str = ""
    service_account_key_json: str = ""
    scopes: list[str] = field(
        default_factory=lambda: ["https://www.googleapis.com/auth/calendar"]
    )


def load_config_from_env() -> ScheduleAgentConfig:
    """
    환경 변수로부터 ScheduleAgentConfig를 로드합니다.

    환경 변수:
        GOOGLE_CALENDAR_ID              : 대상 캘린더 ID. 기본값 "primary".
        GOOGLE_SERVICE_ACCOUNT_KEY_FILE : 서비스 계정 JSON 키 파일 경로.
        GOOGLE_SERVICE_ACCOUNT_JSON     : 서비스 계정 JSON 키 문자열 (파일 경로보다 우선).
    """
    return ScheduleAgentConfig(
        calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        service_account_key_file=os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_FILE", ""),
        service_account_key_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
    )
