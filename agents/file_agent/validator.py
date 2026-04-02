from pathlib import Path
from typing import Protocol


class PathValidatorProtocol(Protocol):
    """
    파일 경로의 유효성을 검사하는 인터페이스입니다.
    """

    def is_allowed(self, target_path: Path | str, allowed_roots: list[Path]) -> bool:
        """
        주어진 경로가 허용된 루트 디렉토리 내에 있는지 확인합니다.

        Args:
            target_path (Path | str): 검사할 대상 경로.
            allowed_roots (list[Path]): 접근 가능한 루트 디렉토리 리스트.

        Returns:
            bool: 허용 여부.
        """
        ...

    def resolve_safe_path(self, target_path: Path | str, allowed_roots: list[Path]) -> Path:
        """
        상대 경로를 절대 경로로 안전하게 변환하고 유효성을 검증합니다.

        Args:
            target_path (Path | str): 변환할 대상 경로.
            allowed_roots (list[Path]): 접근 가능한 루트 디렉토리 리스트.

        Returns:
            Path: 검증된 절대 경로.

        Raises:
            PermissionError: 허용되지 않은 경로 접근 시 발생.
        """
        ...


class PathValidator:
    """
    PathValidatorProtocol의 구체 구현체.
    경로 순회(path traversal) 공격을 방어하고 허용된 루트 외의 접근을 차단합니다.
    """

    def is_allowed(self, target_path: Path | str, allowed_roots: list[Path]) -> bool:
        """주어진 경로가 허용된 루트 디렉토리 중 하나의 하위 경로인지 확인합니다."""
        resolved = Path(target_path).resolve()
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in allowed_roots
        )

    def resolve_safe_path(self, target_path: Path | str, allowed_roots: list[Path]) -> Path:
        """
        경로를 절대 경로로 해석한 뒤 허용 여부를 검증합니다.

        Raises:
            PermissionError: 허용되지 않은 경로 접근 시 발생.
        """
        resolved = Path(target_path).resolve()
        if not self.is_allowed(resolved, allowed_roots):
            raise PermissionError(
                f"접근 거부: '{resolved}' 는 허용된 루트 경로 밖에 있습니다."
            )
        return resolved
