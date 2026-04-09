"""python -m tools.agent_builder 진입점 — stdout UTF-8 강제"""
import io
import sys

# Windows 터미널 cp949 인코딩 오류 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from .cli import main

sys.exit(main())
