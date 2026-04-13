"""
Telegram 전용 HTML 포맷터
- 표준 마크다운을 Telegram HTML 파싱 모드로 변환합니다.
- Telegram HTML: <b>, <i>, <code>, <pre>, <a href="..."> 지원
- 메시지 최대 길이 4096자 준수
"""

import html
import re

_TELEGRAM_MAX_LEN = 3900


class TelegramFormatter:
    @staticmethod
    def format(text: str) -> str:
        if not text:
            return ""

        # 헤더 변환 (### 제목 → <b>제목</b>)
        text = re.sub(r"^#{1,6}\s+(.*)$", r"<b>\1</b>", text, flags=re.MULTILINE)

        # 굵게 (**text** → <b>text</b>)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

        # 이탤릭 (*text* → <i>text</i>)  — 단일 별표만, ** 처리 후
        text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

        # 인라인 코드 (`code` → <code>code</code>)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

        # 길이 제한
        if len(text) > _TELEGRAM_MAX_LEN:
            text = text[:_TELEGRAM_MAX_LEN] + "\n...(이하 생략)"

        return text.strip()

    @staticmethod
    def escape(text: str) -> str:
        """Telegram HTML 모드에서 안전하게 출력할 수 없는 특수문자를 이스케이프합니다."""
        return html.escape(text)
