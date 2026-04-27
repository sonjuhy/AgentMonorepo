import logging
import io
import pytest
from shared_core.agent_logger import SensitiveDataFilter

def test_sensitive_data_filter_masks_secrets():
    # 로그 출력을 캡처하기 위한 스트림 설정
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    
    # 필터 적용
    mask_filter = SensitiveDataFilter()
    handler.addFilter(mask_filter)
    
    test_logger = logging.getLogger("test_security_logger")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    # 테스트할 비밀정보 목록
    secrets = [
        "sk-1234567890abcdef1234567890abcdef",
        "AIzaSyD-1234567890abcdefghijklmnopqrstuv", # Gemini 규격에 맞게 39자
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz12", # GitHub PAT
    ]

    for secret in secrets:
        test_logger.info(f"Connecting with key: {secret}")
        output = log_capture.getvalue()
        assert secret not in output
        assert "***MASKED***" in output
        # 스트림 초기화
        log_capture.truncate(0)
        log_capture.seek(0)

def test_sensitive_data_filter_preserves_normal_text():
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.addFilter(SensitiveDataFilter())
    
    test_logger = logging.getLogger("test_normal_logger")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    normal_msg = "Starting agent: file_agent"
    test_logger.info(normal_msg)
    
    output = log_capture.getvalue()
    assert normal_msg in output
