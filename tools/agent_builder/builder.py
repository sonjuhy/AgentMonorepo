"""
AgentBuilder — 코드와 패키지 리스트로 에이전트 디렉터리를 자동 생성합니다.

사용법 (Python API):
    from tools.agent_builder import AgentBuilder

    builder = AgentBuilder()
    result = builder.build(
        name="weather",
        language="python",
        code=open("weather.py").read(),
        packages=["requests", "beautifulsoup4"],
        port=8010,
        description="날씨 정보 조회 에이전트",
    )
    print(result.agent_dir)   # agents/weather_agent/
    print(result.next_steps)  # 등록 가이드 문자열

생성되는 파일:
  Python 모드:
    agents/{name}_agent/
      __init__.py, user_code.py, agent.py, models.py, protocols.py,
      redis_listener.py, fastapi_app.py, main.py, requirements.txt, Dockerfile

  JavaScript 모드 (위 공통 파일 + 아래 추가):
    agents/{name}_agent/
      user_code.js, _js_shim.js, js_runner.py, package.json
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import templates as T
from .validator import ValidationResult, validate

type Language = Literal["python", "javascript"]

# 모노리포 루트 (tools/ 의 두 단계 위)
_REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass
class BuildResult:
    """에이전트 빌드 결과."""

    agent_dir: Path
    language: Language
    name: str
    files_created: list[str] = field(default_factory=list)
    validation: ValidationResult | None = None
    next_steps: str = ""


class AgentBuilder:
    """
    외부에서 받은 코드와 패키지 리스트로 표준 에이전트 구조를 생성합니다.

    Args:
        repo_root: 모노리포 루트 경로. None이면 이 파일 위치 기준으로 자동 감지.
    """

    def __init__(self, repo_root: Path | None = None) -> None:
        self._root = repo_root or _REPO_ROOT

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def build(
        self,
        name: str,
        language: Language,
        code: str,
        packages: list[str] | None = None,
        *,
        port: int = 8010,
        description: str = "",
        validate_code: bool = True,
        force: bool = False,
    ) -> BuildResult:
        """
        에이전트 디렉터리와 모든 보일러플레이트 파일을 생성합니다.

        Args:
            name:          에이전트 이름 (예: "weather", "my_tool"). 영문/숫자/_ 허용.
            language:      "python" 또는 "javascript"
            code:          user_code.py 또는 user_code.js 내용
            packages:      설치할 패키지 목록 (pip 또는 npm)
            port:          FastAPI 서버 포트 (기본 8010)
            description:   에이전트 설명 (선택)
            validate_code: True면 빌드 전에 문법/패키지 검사 수행
            force:         True면 이미 존재하는 디렉터리를 덮어씁니다

        Returns:
            BuildResult

        Raises:
            ValueError: name이 비어있거나 language가 잘못된 경우
            FileExistsError: 이미 디렉터리가 존재하고 force=False인 경우
        """
        name = _normalize_name(name)
        packages = packages or []
        description = description or f"{name.title()} Agent"

        if language not in ("python", "javascript"):
            raise ValueError(f"language는 'python' 또는 'javascript'여야 합니다: {language!r}")

        agent_dir = self._root / "agents" / f"{name}_agent"

        if agent_dir.exists() and not force:
            raise FileExistsError(
                f"이미 존재합니다: {agent_dir}\n"
                "덮어쓰려면 force=True (CLI: --force)를 사용하세요."
            )

        # 유효성 검사
        validation: ValidationResult | None = None
        if validate_code:
            validation = validate(language, code, packages)

        # 파일 생성
        agent_dir.mkdir(parents=True, exist_ok=True)
        files = self._write_files(agent_dir, name, language, code, packages, port, description)

        result = BuildResult(
            agent_dir=agent_dir,
            language=language,
            name=name,
            files_created=files,
            validation=validation,
            next_steps=_make_next_steps(name, port, self._root),
        )
        return result

    # ── 파일 쓰기 ──────────────────────────────────────────────────────────────

    def _write_files(
        self,
        agent_dir: Path,
        name: str,
        language: Language,
        code: str,
        packages: list[str],
        port: int,
        description: str,
    ) -> list[str]:
        """에이전트 디렉터리에 모든 파일을 씁니다. 생성된 파일 이름 목록 반환."""

        cls = _to_class_name(name)
        vars_ = dict(
            SNAKE_NAME=name,
            CLASS_NAME=cls,
            PORT=str(port),
            DESCRIPTION=description,
        )

        files: list[str] = []

        def write(filename: str, content: str) -> None:
            (agent_dir / filename).write_text(content, encoding="utf-8")
            files.append(filename)

        # ── 공통 파일 (Python/JS 공통 인프라) ─────────────────────────────────

        write("__init__.py", T.render(T.AGENT_INIT_PY, **vars_))
        write("models.py", T.render(T.MODELS_PY, **vars_))
        write("protocols.py", T.render(T.PROTOCOLS_PY, **vars_))
        write("redis_listener.py", T.render(T.REDIS_LISTENER_PY, **vars_))
        write("fastapi_app.py", T.render(T.FASTAPI_APP_PY, **vars_))
        write("main.py", T.render(T.MAIN_PY, **vars_))

        # ── 언어별 파일 ────────────────────────────────────────────────────────

        if language == "python":
            write("user_code.py", code)
            write("agent.py", T.render(T.AGENT_PY_PYTHON, **vars_))
            write("requirements.txt", _make_requirements(packages))
            write("Dockerfile", T.render(T.DOCKERFILE_PYTHON, **vars_))

        else:  # javascript
            write("user_code.js", code)
            write("_js_shim.js", T.JS_SHIM)
            write("js_runner.py", T.JS_RUNNER_PY)
            write("agent.py", T.render(T.AGENT_PY_JS, **vars_))
            write("requirements.txt", _make_requirements([]))  # Python infra only
            write("package.json", T.render(T.PACKAGE_JSON, **{
                **vars_,
                "NPM_DEPS": _make_npm_deps(packages),
            }))
            write("Dockerfile", T.render(T.DOCKERFILE_JS, **vars_))

        return files


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """에이전트 이름을 snake_case 소문자로 정규화합니다."""
    name = name.strip().lower()
    # 공백/하이픈 → 언더스코어
    name = re.sub(r"[\s\-]+", "_", name)
    # 허용되지 않는 문자 제거
    name = re.sub(r"[^a-z0-9_]", "", name)
    # _agent 접미사 제거 (자동으로 붙임)
    name = re.sub(r"_agent$", "", name)
    if not name:
        raise ValueError("에이전트 이름이 비어있습니다.")
    if not name[0].isalpha():
        raise ValueError(f"에이전트 이름은 영문자로 시작해야 합니다: {name!r}")
    return name


def _to_class_name(snake_name: str) -> str:
    """snake_case → PascalCase 변환 (예: my_tool → MyTool)."""
    return "".join(part.capitalize() for part in snake_name.split("_"))


def _make_requirements(user_packages: list[str]) -> str:
    """requirements.txt 내용을 생성합니다."""
    packages_lines = "\n".join(user_packages) if user_packages else "# (패키지 없음)"
    return T.render(T.REQUIREMENTS_TXT, PACKAGES_LINES=packages_lines)


def _make_npm_deps(packages: list[str]) -> str:
    """package.json의 dependencies 섹션 내용을 생성합니다."""
    if not packages:
        return '    "# no-packages": "0.0.0"'
    lines = [f'    "{pkg}": "*"' for pkg in packages]
    return ",\n".join(lines)


def _make_next_steps(name: str, port: int, repo_root: Path) -> str:
    """등록/빌드 안내 문자열을 생성합니다."""
    schema_path = repo_root / "shared_core" / "messaging" / "schema.py"
    compose_snippet = T.render(T.COMPOSE_SNIPPET, SNAKE_NAME=name, PORT=str(port))

    lines = [
        "── 다음 단계 ──────────────────────────────────────────────────────────",
        "",
        "1. AgentName 등록",
        f"   {schema_path}",
        f'   type AgentName = Literal[..., "{name}"]  <- 추가',
        "",
        "2. docker-compose.yml에 서비스 추가 (services: 아래에 붙여넣기)",
        compose_snippet,
        "3. 이미지 빌드",
        f"   docker-compose build {name}_agent",
        "",
        "4. 실행 (server 모드)",
        f"   docker-compose up {name}_agent",
        "   # 또는 OrchestraManager를 통해 Redis 큐로 디스패치",
        "",
        "5. 테스트 (HTTP 직접 호출)",
        f"   curl -X POST http://localhost:{port}/dispatch \\",
        f'     -H \'Content-Type: application/json\' \\',
        f'     -d \'{{\"task_id\": \"test-001\", \"params\": {{}}}}\'',
    ]
    return "\n".join(lines)
