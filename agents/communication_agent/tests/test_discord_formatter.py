import pytest
from agents.communication_agent.discord.formatter import DiscordFormatter

def test_discord_formatter_headers():
    text = "### Header 3\n## Header 2\n# Header 1"
    formatted = DiscordFormatter.format(text)
    assert "**Header 3**" in formatted
    assert "**Header 2**" in formatted
    assert "**Header 1**" in formatted

def test_discord_formatter_length_limit():
    long_text = "A" * 4000
    formatted = DiscordFormatter.format(long_text)
    assert len(formatted) <= 3900 + len("\n...(이하 생략)")
    assert formatted.endswith("...(이하 생략)")

def test_discord_formatter_empty():
    assert DiscordFormatter.format("") == ""
