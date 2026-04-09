"""
Agent Builder 유효성 검사 모듈

수행하는 검사:
  - Python: ast.parse()로 문법 오류 검출
  - JavaScript: node --check 로 문법 오류 검출 (Node.js 설치 시)
  - Python 패키지: pip install --dry-run 으로 존재 여부 확인
  - JavaScript 패키지: npm pack --dry-run 은 느리므로 이름 형식만 검사

결과:
  ValidationResult.ok == True   → 검사 통과
  ValidationResult.ok == False  → 검사 실패, errors 리스트 참조
  ValidationResult.warnings     → 경고 (통과하지만 주의 필요)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# ── Python 검사 ───────────────────────────────────────────────────────────────

def validate_python(code: str, packages: list[str]) -> ValidationResult:
    """Python 코드 문법과 패키지 존재 여부를 검사합니다."""
    result = ValidationResult()

    # 1. 문법 검사
    _check_python_syntax(code, result)
    if not result.ok:
        return result  # 문법 오류면 패키지 검사 불필요

    # 2. run() 함수 존재 여부
    _check_python_run_function(code, result)

    # 3. 패키지 가용 여부
    if packages:
        _check_python_packages(packages, result)

    return result


def _check_python_syntax(code: str, result: ValidationResult) -> None:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        result.fail(f"Python 문법 오류 (line {exc.lineno}): {exc.msg}")


def _check_python_run_function(code: str, result: ValidationResult) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return  # 이미 위에서 처리됨

    has_run = any(
        isinstance(node, ast.FunctionDef) and node.name == "run"
        for node in ast.walk(tree)
    )
    if not has_run:
        result.warn(
            "user_code.py에 run(params: dict) -> dict 함수가 없습니다. "
            "에이전트 실행 시 ImportError가 발생합니다."
        )


def _check_python_packages(packages: list[str], result: ValidationResult) -> None:
    """pip install --dry-run 으로 패키지 해석 가능 여부를 확인합니다."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", *packages],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            # pip 오류 메시지에서 문제 패키지를 추출
            stderr = proc.stderr.strip()
            result.warn(
                f"pip --dry-run 경고 (빌드 시 실제 설치 재시도됨):\n  {stderr[:300]}"
            )
    except FileNotFoundError:
        result.warn("pip을 찾을 수 없어 패키지 검사를 건너뜁니다.")
    except subprocess.TimeoutExpired:
        result.warn("pip --dry-run 타임아웃 (30s). 패키지 검사를 건너뜁니다.")


# ── JavaScript 검사 ───────────────────────────────────────────────────────────

def validate_javascript(code: str, packages: list[str]) -> ValidationResult:
    """JavaScript 코드 문법과 패키지 이름 형식을 검사합니다."""
    result = ValidationResult()

    # 1. 문법 검사 (node --check)
    _check_js_syntax(code, result)

    # 2. module.exports 패턴 확인
    _check_js_exports(code, result)

    # 3. 패키지 이름 형식 검사 (npm 스펙)
    if packages:
        _check_npm_package_names(packages, result)

    return result


def _check_js_syntax(code: str, result: ValidationResult) -> None:
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        proc = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        os.unlink(tmp_path)

        if proc.returncode != 0:
            # node 오류 메시지에서 파일 경로를 제거해 깔끔하게 출력
            err = proc.stderr.replace(tmp_path, "user_code.js").strip()
            result.fail(f"JavaScript 문법 오류:\n  {err}")

    except FileNotFoundError:
        result.warn(
            "Node.js가 설치되어 있지 않아 JavaScript 문법 검사를 건너뜁니다. "
            "Dockerfile 빌드 후 런타임에서 확인하세요."
        )
    except subprocess.TimeoutExpired:
        result.warn("node --check 타임아웃. 문법 검사를 건너뜁니다.")
    except Exception as exc:
        result.warn(f"JavaScript 문법 검사 중 예기치 않은 오류: {exc}")


def _check_js_exports(code: str, result: ValidationResult) -> None:
    """module.exports = { run } 또는 exports.run 패턴을 확인합니다."""
    has_run_export = bool(
        re.search(r"module\.exports\s*=", code)
        or re.search(r"exports\.run\s*=", code)
        or re.search(r"export\s+(default\s+)?function\s+run", code)
        or re.search(r"export\s+\{[^}]*run[^}]*\}", code)
    )
    if not has_run_export:
        result.warn(
            "user_code.js에서 run 함수가 내보내지지 않는 것 같습니다. "
            "module.exports = { run } 또는 exports.run = ... 을 추가하세요."
        )


def _check_npm_package_names(packages: list[str], result: ValidationResult) -> None:
    """npm 패키지 이름 형식을 검사합니다 (실제 레지스트리 조회 없음)."""
    # npm 패키지 이름: 소문자, 숫자, -, _, . / 또는 @scope/name 형식
    pattern = re.compile(r"^(@[a-z0-9\-_]+/)?[a-z0-9\-_.]+(@[\w\.\-]+)?$")
    for pkg in packages:
        if not pattern.match(pkg.lower()):
            result.warn(
                f"패키지 이름 형식이 비표준입니다: '{pkg}'. "
                "npm install 실패 시 package.json을 직접 수정하세요."
            )


# ── 공통 진입점 ───────────────────────────────────────────────────────────────

def validate(language: str, code: str, packages: list[str]) -> ValidationResult:
    """언어에 맞는 검사를 실행하고 ValidationResult를 반환합니다."""
    if language == "python":
        return validate_python(code, packages)
    elif language == "javascript":
        return validate_javascript(code, packages)
    else:
        result = ValidationResult()
        result.fail(f"지원하지 않는 언어: '{language}'. python 또는 javascript를 사용하세요.")
        return result
