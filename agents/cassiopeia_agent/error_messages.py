"""
사용자 친화적 오류 메시지 변환 모듈

기술적 에러 코드를 한국어 자연어 메시지로 변환합니다.
에이전트 결과의 error.code 또는 내부 오류 코드에 사용합니다.
"""
from __future__ import annotations

DEFAULT_ERROR_MESSAGE = "예상치 못한 오류가 발생했습니다. 문제가 지속되면 관리자에게 문의해주세요."

_ERROR_MESSAGE_MAP: dict[str, str] = {
    "TIMEOUT": "요청 처리 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.",
    "RATE_LIMIT": "요청이 너무 많습니다. {retry_after}초 후에 다시 시도해주세요.",
    "INTERNAL_ERROR": "내부 오류가 발생했습니다. 문제가 지속되면 관리자에게 문의해주세요.",
    "EXECUTION_ERROR": "작업 실행 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
    "EXTERNAL_API_ERROR": "외부 서비스 연결에 실패했습니다. 잠시 후 다시 시도해주세요.",
    "NOT_FOUND": "요청한 항목을 찾을 수 없습니다.",
    "PARSE_ERROR": "요청 형식이 올바르지 않습니다. 입력 내용을 확인해주세요.",
    "CANCELLED": "작업이 취소되었습니다.",
    "INVALID_PARAMS": "입력값이 올바르지 않습니다. 내용을 확인 후 다시 시도해주세요.",
    "AGENT_UNAVAILABLE": "해당 기능을 담당하는 에이전트를 현재 사용할 수 없습니다. 잠시 후 다시 시도해주세요.",
    "DUPLICATE_REQUEST": "동일한 요청이 이미 처리 중입니다. 기존 작업이 완료될 때까지 기다려주세요.",
    "APPROVAL_TIMEOUT": "승인 대기 시간이 초과되었습니다. 작업이 자동으로 취소되었습니다.",
    "APPROVAL_REJECTED": "작업이 취소되었습니다.",
}


def get_user_message(error_code: str, **kwargs: object) -> str:
    """에러 코드를 사용자 친화적 한국어 메시지로 변환합니다.

    Args:
        error_code: 기술적 에러 코드 (예: "TIMEOUT", "RATE_LIMIT")
        **kwargs: 메시지 내 포맷 파라미터 (예: retry_after=30)

    Returns:
        사용자에게 보여줄 한국어 메시지
    """
    template = _ERROR_MESSAGE_MAP.get(error_code)
    if template is None:
        return DEFAULT_ERROR_MESSAGE
    try:
        return template.format(**kwargs)
    except KeyError:
        # 포맷 파라미터 누락 시 파라미터 없이 재시도
        try:
            return template.format()
        except KeyError:
            return template.split("{")[0].strip() or DEFAULT_ERROR_MESSAGE


def build_error_response(error_code: str, **kwargs: object) -> dict[str, str]:
    """API 오류 응답 바디를 생성합니다.

    Returns:
        {"error_code": ..., "message": ...} 형태의 dict
    """
    return {
        "error_code": error_code,
        "message": get_user_message(error_code, **kwargs),
    }
