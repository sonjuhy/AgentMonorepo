from pathlib import Path
from dataclasses import dataclass, field

@dataclass(frozen=True)
class FileAgentConfig:
    """
    파일 관리 에이전트의 설정 정보를 관리합니다.

    Attributes:
        allowed_roots (list[Path]): 에이전트가 접근 가능한 루트 경로 목록.
        max_file_size_mb (int): 처리 가능한 최대 파일 크기 (MB).
    """
    allowed_roots: list[Path] = field(default_factory=list)
    max_file_size_mb: int = 10

def load_config_from_env() -> FileAgentConfig:
    """
    환경 변수로부터 설정을 로드합니다.

    환경 변수:
        FILE_AGENT_ALLOWED_ROOTS: 콤마로 구분된 허용 루트 경로 목록.
        FILE_AGENT_MAX_FILE_SIZE_MB: 최대 파일 크기 (MB). 기본값 10.

    Returns:
        FileAgentConfig: 로드된 설정 객체.
    """
    import os

    roots_env = os.environ.get("FILE_AGENT_ALLOWED_ROOTS", "")
    allowed_roots = [Path(p.strip()) for p in roots_env.split(",") if p.strip()]
    max_size_mb = int(os.environ.get("FILE_AGENT_MAX_FILE_SIZE_MB", "10"))
    return FileAgentConfig(allowed_roots=allowed_roots, max_file_size_mb=max_size_mb)
