"""
Agent Builder CLI 진입점

사용법:
    # Python 에이전트 (파일로 코드 전달)
    python -m tools.agent_builder \\
        --name weather \\
        --language python \\
        --code agents/my_code/weather.py \\
        --packages requests beautifulsoup4 \\
        --port 8010 \\
        --description "날씨 정보 조회 에이전트"

    # JavaScript 에이전트 (파일로 코드 전달)
    python -m tools.agent_builder \\
        --name translator \\
        --language javascript \\
        --code translate.js \\
        --packages axios \\
        --port 8011

    # 인라인 코드 (짧은 코드용)
    python -m tools.agent_builder \\
        --name echo \\
        --language python \\
        --code-inline "def run(params): return params" \\
        --port 8012

    # 이미 존재하는 디렉터리 덮어쓰기
    python -m tools.agent_builder ... --force

    # 유효성 검사 건너뛰기
    python -m tools.agent_builder ... --no-validate

    # 예시 코드 출력
    python -m tools.agent_builder --example python
    python -m tools.agent_builder --example javascript
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import templates as T
from .builder import AgentBuilder
from .validator import ValidationResult


def _print_validation(result: ValidationResult, verbose: bool = False) -> bool:
    """검사 결과를 출력하고, 통과 여부를 반환합니다."""
    if result.warnings:
        for w in result.warnings:
            print(f"  ⚠  {w}")

    if not result.ok:
        for e in result.errors:
            print(f"  ✗  {e}", file=sys.stderr)
        return False

    if verbose:
        print("  ✓  유효성 검사 통과")
    return True


def _print_files(files: list[str], agent_dir: Path) -> None:
    print(f"\n생성된 파일 ({agent_dir}):")
    for f in files:
        print(f"  ├── {f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.agent_builder",
        description="코드와 패키지 리스트로 에이전트를 자동 생성합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── 예시 출력 (다른 인수 불필요) ──────────────────────────────────────────
    parser.add_argument(
        "--example",
        choices=["python", "javascript"],
        metavar="{python,javascript}",
        help="예시 user_code 파일을 출력하고 종료합니다.",
    )

    # ── 필수/핵심 인수 ────────────────────────────────────────────────────────
    parser.add_argument(
        "--name", "-n",
        help="에이전트 이름 (예: weather). 디렉터리 이름: agents/{name}_agent/",
    )
    parser.add_argument(
        "--language", "-l",
        choices=["python", "javascript"],
        default="python",
        help="사용자 코드 언어 (기본값: python)",
    )

    # 코드 입력: 파일 경로 또는 인라인 (둘 중 하나 필수)
    code_group = parser.add_mutually_exclusive_group()
    code_group.add_argument(
        "--code", "-c",
        metavar="FILE",
        help="user_code 파일 경로 (.py 또는 .js)",
    )
    code_group.add_argument(
        "--code-inline",
        metavar="CODE",
        help="user_code 인라인 문자열 (짧은 코드용)",
    )

    parser.add_argument(
        "--packages", "-p",
        nargs="*",
        default=[],
        metavar="PKG",
        help="설치할 패키지 목록 (pip 또는 npm). 예: requests beautifulsoup4",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8010,
        help="FastAPI 서버 포트 (기본값: 8010)",
    )
    parser.add_argument(
        "--description", "-d",
        default="",
        help="에이전트 설명 (선택)",
    )

    # ── 옵션 ──────────────────────────────────────────────────────────────────
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="이미 존재하는 디렉터리를 덮어씁니다.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="문법/패키지 유효성 검사를 건너뜁니다.",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="모노리포 루트 경로 (기본값: 자동 감지)",
    )

    args = parser.parse_args(argv)

    # ── --example 처리 ────────────────────────────────────────────────────────
    if args.example:
        if args.example == "python":
            print(T.render(T.PYTHON_USER_CODE_EXAMPLE, CLASS_NAME="Example", SNAKE_NAME="example"))
        else:
            print(T.render(T.JS_USER_CODE_EXAMPLE, CLASS_NAME="Example", SNAKE_NAME="example"))
        return 0

    # ── 필수 인수 확인 ────────────────────────────────────────────────────────
    if not args.name:
        parser.error("--name 인수가 필요합니다.")
    if not args.code and not args.code_inline:
        parser.error("--code 또는 --code-inline 중 하나가 필요합니다.")

    # ── 코드 로드 ─────────────────────────────────────────────────────────────
    if args.code:
        code_path = Path(args.code)
        if not code_path.exists():
            print(f"✗ 파일을 찾을 수 없습니다: {code_path}", file=sys.stderr)
            return 1
        code = code_path.read_text(encoding="utf-8")
        print(f"코드 파일 로드: {code_path} ({len(code)} bytes)")
    else:
        code = args.code_inline

    # ── 빌드 실행 ─────────────────────────────────────────────────────────────
    repo_root = Path(args.repo_root) if args.repo_root else None
    builder = AgentBuilder(repo_root=repo_root)

    print(f"\n에이전트 빌드 시작: {args.name} ({args.language})")

    if not args.no_validate:
        print("유효성 검사 중...")
        from .validator import validate as _validate
        validation = _validate(args.language, code, args.packages or [])
        ok = _print_validation(validation, verbose=True)
        if not ok:
            print("\n✗ 유효성 검사 실패. 코드를 수정하거나 --no-validate를 사용하세요.", file=sys.stderr)
            return 1
    else:
        print("유효성 검사 건너뜀 (--no-validate)")

    try:
        result = builder.build(
            name=args.name,
            language=args.language,
            code=code,
            packages=args.packages or [],
            port=args.port,
            description=args.description,
            validate_code=False,  # 위에서 이미 검사 완료
            force=args.force,
        )
    except FileExistsError as exc:
        print(f"\n✗ {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\n✗ 입력 오류: {exc}", file=sys.stderr)
        return 1

    # ── 결과 출력 ─────────────────────────────────────────────────────────────
    _print_files(result.files_created, result.agent_dir)
    print(f"\n✓ 에이전트 생성 완료: {result.agent_dir}")
    print()
    print(result.next_steps)

    return 0


if __name__ == "__main__":
    sys.exit(main())
