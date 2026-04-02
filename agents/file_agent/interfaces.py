from dataclasses import dataclass, field
from typing import Protocol, Literal, Any
from pathlib import Path

type FileOperationStatus = Literal["success", "error", "permission_denied"]

@dataclass
class FileOperationResult:
    """
    파일 작업 결과를 나타내는 데이터 클래스입니다.

    Attributes:
        status (FileOperationStatus): 작업 상태.
        message (str): 상세 결과 메시지.
        data (Any | None): 읽기 작업 시 반환되는 데이터 등 추가 정보.
    """
    status: FileOperationStatus
    message: str
    data: Any | None = field(default=None)

class FileAgentProtocol(Protocol):
    """
    파일 CRUD 작업을 수행하는 에이전트의 추상 인터페이스입니다.
    """

    async def read_file(self, file_path: Path | str) -> FileOperationResult:
        """
        내용을 읽어옵니다.

        Args:
            file_path (Path | str): 읽을 파일의 경로.

        Returns:
            FileOperationResult: 작업 결과 및 파일 내용.
        """
        ...

    async def write_file(self, file_path: Path | str, content: str, overwrite: bool = False) -> FileOperationResult:
        """
        파일을 생성하거나 내용을 작성합니다.

        Args:
            file_path (Path | str): 저장할 파일 경로.
            content (str): 작성할 내용.
            overwrite (bool): 기존 파일 덮어쓰기 여부. Defaults to False.

        Returns:
            FileOperationResult: 작업 성공 여부.
        """
        ...

    async def update_file(self, file_path: Path | str, content: str, append: bool = True) -> FileOperationResult:
        """
        기존 파일의 내용을 수정합니다.

        Args:
            file_path (Path | str): 수정할 파일 경로.
            content (str): 추가 또는 교체할 내용.
            append (bool): 기존 내용 뒤에 추가할지 여부. Defaults to True.

        Returns:
            FileOperationResult: 작업 성공 여부.
        """
        ...

    async def delete_file(self, file_path: Path | str) -> FileOperationResult:
        """
        파일을 삭제합니다.

        Args:
            file_path (Path | str): 삭제할 파일 경로.

        Returns:
            FileOperationResult: 작업 성공 여부.
        """
        ...
