"""
Slack 메시지 정제 모듈
- @bot 멘션, 채널 멘션 등 불필요한 태그를 제거하여 순수 텍스트를 추출합니다.
"""

import re


class MessageCleaner:
    """
    Slack 메시지에서 시스템 태그를 제거하고 순수 텍스트를 반환합니다.

    처리 대상:
        - 사용자 멘션: <@U12345>
        - 채널 멘션:   <#C12345|general>
        - URL 태그:    <https://example.com|표시텍스트>  → 표시텍스트만 유지
        - &amp; &lt; &gt; HTML 엔티티 디코딩
    """

    # <@U...> 또는 <@W...> 형태의 사용자 멘션
    _USER_MENTION = re.compile(r"<@[UW][A-Z0-9]+>")

    # <#C...|채널명> 형태의 채널 멘션
    _CHANNEL_MENTION = re.compile(r"<#[A-Z0-9]+\|[^>]*>")

    # <!here>, <!channel>, <!everyone> 등 특수 멘션
    _SPECIAL_MENTION = re.compile(r"<!(?:here|channel|everyone)(?:\|[^>]*)?>")

    # <URL|표시텍스트> → 표시텍스트, <URL> → URL 제거
    _LINK = re.compile(r"<(https?://[^|>]+)(?:\|([^>]+))?>")

    @classmethod
    def clean(cls, text: str) -> str:
        """
        Slack 메시지 텍스트에서 불필요한 태그를 제거합니다.

        Args:
            text (str): 원본 Slack 메시지 텍스트.

        Returns:
            str: 태그가 제거된 순수 텍스트.

        Example:
            >>> MessageCleaner.clean("<@U12345> 내일 일정 알려줘")
            "내일 일정 알려줘"
        """
        # 사용자/채널/특수 멘션 제거
        text = cls._USER_MENTION.sub("", text)
        text = cls._CHANNEL_MENTION.sub("", text)
        text = cls._SPECIAL_MENTION.sub("", text)

        # 링크: 표시텍스트가 있으면 유지, 없으면 URL 제거
        text = cls._LINK.sub(lambda m: m.group(2) if m.group(2) else "", text)

        # HTML 엔티티 디코딩
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

        return text.strip()
