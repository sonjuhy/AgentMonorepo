"""
File Agent 구체 구현체
- FileAgentProtocol 구현: read / write / update / delete
- Redis 브로커를 통한 메시지 수신 및 결과 발행
- ephemeral-docker-ops 전략: 메시지 1건 처리 후 자연 종료
"""

import os
from pathlib import Path

from shared_core.messaging.broker import RedisMessageBroker
from shared_core.messaging.schema import AgentMessage

from .config import FileAgentConfig, load_config_from_env
from .interfaces import FileOperationResult
from .validator import PathValidator, PathValidatorProtocol


class FileAgent:
    """
    FileAgentProtocol의 구체 구현체.

    설정된 허용 루트 내에서 파일 CRUD 작업을 수행하고,
    Redis 브로커로부터 AgentMessage를 수신해 작업을 실행한 뒤 결과를 발신자에게 반환합니다.
    """

    agent_name: str = "file-agent"

    def __init__(
        self,
        config: FileAgentConfig | None = None,
        validator: PathValidatorProtocol | None = None,
    ) -> None:
        self._config = config or load_config_from_env()
        self._validator = validator or PathValidator()

    # ------------------------------------------------------------------ #
    # FileAgentProtocol 구현                                               #
    # ------------------------------------------------------------------ #

    async def read_file(self, file_path: Path | str) -> FileOperationResult:
        """허용된 경로의 파일 내용을 읽어 반환합니다."""
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > self._config.max_file_size_mb:
                return FileOperationResult(
                    status="error",
                    message=(
                        f"파일 크기 초과: {size_mb:.1f}MB "
                        f"(최대 {self._config.max_file_size_mb}MB)"
                    ),
                )
            content = path.read_text(encoding="utf-8")
            return FileOperationResult(status="success", message="읽기 완료", data=content)
        except PermissionError as e:
            return FileOperationResult(status="permission_denied", message=str(e))
        except FileNotFoundError:
            return FileOperationResult(
                status="error", message=f"파일을 찾을 수 없습니다: {file_path}"
            )
        except Exception as e:
            return FileOperationResult(status="error", message=f"읽기 실패: {e}")

    async def write_file(
        self,
        file_path: Path | str,
        content: str,
        overwrite: bool = False,
    ) -> FileOperationResult:
        """파일을 생성하거나 내용을 씁니다. overwrite=False 이면 기존 파일을 덮어쓰지 않습니다."""
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if path.exists() and not overwrite:
                return FileOperationResult(
                    status="error",
                    message=f"파일이 이미 존재합니다 (overwrite=False): {path}",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return FileOperationResult(status="success", message=f"쓰기 완료: {path}")
        except PermissionError as e:
            return FileOperationResult(status="permission_denied", message=str(e))
        except Exception as e:
            return FileOperationResult(status="error", message=f"쓰기 실패: {e}")

    async def update_file(
        self,
        file_path: Path | str,
        content: str,
        append: bool = True,
    ) -> FileOperationResult:
        """기존 파일을 수정합니다. append=True 이면 내용을 뒤에 추가, False 이면 전체 교체합니다."""
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if not path.exists():
                return FileOperationResult(
                    status="error", message=f"파일이 존재하지 않습니다: {path}"
                )
            if append:
                with path.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                path.write_text(content, encoding="utf-8")
            mode = "추가" if append else "교체"
            return FileOperationResult(status="success", message=f"업데이트({mode}) 완료: {path}")
        except PermissionError as e:
            return FileOperationResult(status="permission_denied", message=str(e))
        except Exception as e:
            return FileOperationResult(status="error", message=f"업데이트 실패: {e}")

    async def delete_file(self, file_path: Path | str) -> FileOperationResult:
        """파일을 삭제합니다."""
        try:
            path = self._validator.resolve_safe_path(file_path, self._config.allowed_roots)
            if not path.exists():
                return FileOperationResult(
                    status="error", message=f"파일이 존재하지 않습니다: {path}"
                )
            path.unlink()
            return FileOperationResult(status="success", message=f"삭제 완료: {path}")
        except PermissionError as e:
            return FileOperationResult(status="permission_denied", message=str(e))
        except Exception as e:
            return FileOperationResult(status="error", message=f"삭제 실패: {e}")

    # ------------------------------------------------------------------ #
    # 브로커 연동                                                           #
    # ------------------------------------------------------------------ #

    async def _dispatch(self, message: AgentMessage) -> FileOperationResult:
        """수신된 AgentMessage의 action에 따라 적절한 파일 작업을 실행합니다."""
        payload = message.payload
        action = message.action

        match action:
            case "read_file":
                return await self.read_file(payload["file_path"])
            case "write_file":
                return await self.write_file(
                    payload["file_path"],
                    payload["content"],
                    payload.get("overwrite", False),
                )
            case "update_file":
                return await self.update_file(
                    payload["file_path"],
                    payload["content"],
                    payload.get("append", True),
                )
            case "delete_file":
                return await self.delete_file(payload["file_path"])
            case _:
                return FileOperationResult(
                    status="error", message=f"알 수 없는 액션: {action}"
                )

    async def run(self) -> None:
        """
        에이전트 사이클의 진입점.
        Redis 채널 ``agent:file`` 을 구독하고, 메시지 1건을 처리한 뒤 자연 종료합니다.
        (ephemeral-docker-ops 전략 준수: while True / asyncio.sleep 반복 금지)
        """
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        print(f"[{self.agent_name}] 실행 시작 (Redis: {redis_url})")

        async with RedisMessageBroker(redis_url) as broker:
            async for message in broker.subscribe("file"):
                print(
                    f"[{self.agent_name}] 수신: action={message.action}, "
                    f"sender={message.sender}"
                )

                result = await self._dispatch(message)

                response = AgentMessage(
                    sender="file",
                    receiver=message.sender,
                    action=f"{message.action}_result",
                    payload={
                        "status": result.status,
                        "message": result.message,
                        "data": result.data,
                    },
                )
                published = await broker.publish(response)
                status_label = "발행 완료" if published else "발행 실패"
                print(
                    f"[{self.agent_name}] {status_label}: "
                    f"result={result.status} → {message.sender}"
                )
                break  # ephemeral: 1건 처리 후 자연 종료

        print(f"[{self.agent_name}] 실행 종료")
