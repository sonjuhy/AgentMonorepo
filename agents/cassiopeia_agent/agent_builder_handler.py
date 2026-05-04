"""
AgentBuilderHandler — OrchestraManager 연동 에이전트 빌더 핸들러

tools.agent_builder.AgentBuilder를 asyncio 이벤트 루프에서 안전하게 호출합니다.
AgentBuilder.build()는 subprocess(pip --dry-run 등)를 사용하는 동기 함수이므로
run_in_executor를 통해 스레드풀에서 실행합니다.

OrchestraManager는 이 핸들러를 직접 호출합니다 (Redis 큐 불필요).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("cassiopeia_agent.agent_builder_handler")

# 허용 언어
_SUPPORTED_LANGUAGES = frozenset({"python", "javascript"})


class AgentBuilderHandler:
    """
    OrchestraManager에서 호출하는 AgentBuilder 비동기 래퍼.

    build_agent()는 params dict에서 파라미터를 추출하고
    tools.agent_builder.AgentBuilder.build()를 스레드에서 실행합니다.
    """

    async def build_agent(
        self,
        params: dict[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        """
        에이전트를 빌드하고 AgentResult 형식으로 결과를 반환합니다.

        NLU가 추출하는 params 키:
            name        (str, 필수)  — 에이전트 이름 (예: "weather")
            language    (str)        — "python" | "javascript" (기본값: "python")
            code        (str, 필수)  — user_code 소스 문자열
            packages    (list[str])  — 설치할 패키지 목록
            port        (int)        — FastAPI 서버 포트 (기본값: 8010)
            description (str)        — 에이전트 설명
            force       (bool)       — 기존 디렉터리 덮어쓰기 (기본값: False)
        """
        name = str(params.get("name", "")).strip()
        language = str(params.get("language", "python")).lower().strip()
        code = str(params.get("code", "")).strip()
        packages: list[str] = [
            str(p).strip() for p in (params.get("packages") or []) if str(p).strip()
        ]
        port = int(params.get("port", 8010))
        description = str(params.get("description", ""))
        force = bool(params.get("force", False))

        # 필수 파라미터 검증
        if not name:
            return _make_error(task_id, "INVALID_PARAMS", "에이전트 이름(name)이 필요합니다.")
        if not code:
            return _make_error(
                task_id, "INVALID_PARAMS",
                "실행할 코드(code)가 필요합니다. "
                "user_code.py의 run(params: dict) -> dict 구현을 제공해 주세요."
            )
        if language not in _SUPPORTED_LANGUAGES:
            return _make_error(
                task_id, "INVALID_PARAMS",
                f"language는 'python' 또는 'javascript'여야 합니다: {language!r}"
            )

        logger.info(
            "[AgentBuilderHandler] 빌드 시작 name=%s language=%s packages=%s port=%d",
            name, language, packages, port,
        )

        try:
            loop = asyncio.get_running_loop()
            build_result = await loop.run_in_executor(
                None,
                _run_builder_sync,
                name, language, code, packages, port, description, force,
            )
        except FileExistsError as exc:
            return _make_error(
                task_id, "FILE_EXISTS",
                f"{exc}\n에이전트를 덮어쓰려면 force=true 파라미터를 추가하세요."
            )
        except ValueError as exc:
            return _make_error(task_id, "INVALID_PARAMS", str(exc))
        except Exception as exc:
            logger.exception("[AgentBuilderHandler] 빌드 중 예외 발생")
            return _make_error(task_id, "BUILD_ERROR", str(exc))

        # 검증 경고 수집
        warnings: list[str] = []
        if build_result.validation and build_result.validation.warnings:
            warnings = build_result.validation.warnings
            for w in warnings:
                logger.warning("[AgentBuilderHandler] 검증 경고: %s", w)

        summary = (
            f"`{build_result.name}_agent` 에이전트가 성공적으로 생성되었습니다. "
            f"({len(build_result.files_created)}개 파일, {language})"
        )
        if warnings:
            summary += f"\n\n⚠️ 경고:\n" + "\n".join(f"- {w}" for w in warnings)

        logger.info(
            "[AgentBuilderHandler] 빌드 완료 name=%s files=%d",
            build_result.name, len(build_result.files_created),
        )

        return {
            "task_id": task_id,
            "status": "COMPLETED",
            "result_data": {
                "summary": summary,
                "raw_text": build_result.next_steps,
                "agent_name": build_result.name,
                "agent_dir": str(build_result.agent_dir),
                "files_created": build_result.files_created,
                "language": build_result.language,
                "port": port,
                "validation_warnings": warnings,
            },
            "error": None,
            "usage_stats": {
                "files_created": len(build_result.files_created),
                "language": language,
            },
        }


# ── 스레드에서 실행되는 동기 빌더 ────────────────────────────────────────────

def _run_builder_sync(
    name: str,
    language: str,
    code: str,
    packages: list[str],
    port: int,
    description: str,
    force: bool,
):
    """
    동기 블로킹 함수 — run_in_executor로 스레드풀에서 실행됩니다.
    AgentBuilder.build()는 subprocess를 호출하므로 직접 await 불가.
    """
    from tools.agent_builder.builder import AgentBuilder
    builder = AgentBuilder()
    return builder.build(
        name=name,
        language=language,
        code=code,
        packages=packages,
        port=port,
        description=description,
        validate_code=True,
        force=force,
    )


def _make_error(task_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": "FAILED",
        "result_data": {},
        "error": {"code": code, "message": message, "traceback": None},
        "usage_stats": {},
    }
