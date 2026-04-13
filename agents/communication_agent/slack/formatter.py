"""
Slack 전용 mrkdwn 포맷터
- 표준 마크다운(Gfm)을 Slack mrkdwn 규격으로 변환합니다.
"""

import re

class SlackFormatter:
    @staticmethod
    def format(text: str) -> str:
        if not text:
            return ""

        # 1. 헤더 변환 (### 제목 -> *제목*)
        text = re.sub(r"^#+\s+(.*)$", r"*\1*", text, flags=re.MULTILINE)

        # 2. 굵게 처리 변환 (표준 **text** -> Slack *text*)
        # 주의: Slack은 별표 1개(*)가 굵게입니다.
        text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)

        # 3. 이력서/리스트 스타일 보정
        # Slack은 표준 마크다운 리스트를 어느 정도 지원하지만, 가독성을 위해 보정할 수 있습니다.

        # 4. 언더라인이나 기타 표준 마크다운 요소 제거/변경 (Slack 미지원)
        
        return text.strip()
