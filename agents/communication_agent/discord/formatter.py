"""
Discord 전용 마크다운 포맷터
- 표준 마크다운을 Discord 마크다운 규격으로 변환합니다.
- Discord embed 필드 최대 길이(4096자)를 준수합니다.
"""

import re

_DISCORD_MAX_LEN = 3900  # embed description 안전 한도


class DiscordFormatter:
    @staticmethod
    def format(text: str) -> str:
        if not text:
            return ""

        # 헤더 변환 (## 제목 → **제목**\n)
        text = re.sub(r"^#{1,6}\s+(.*)$", r"**\1**", text, flags=re.MULTILINE)

        # 길이 제한
        if len(text) > _DISCORD_MAX_LEN:
            text = text[:_DISCORD_MAX_LEN] + "\n...(이하 생략)"

        return text.strip()
