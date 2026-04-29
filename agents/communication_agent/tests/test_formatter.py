import pytest
from agents.communication_agent.slack.formatter import SlackFormatter

def test_formatter_markdown_bold():
    text = "This is **bold** text."
    assert SlackFormatter.format(text) == "This is *bold* text."

def test_formatter_headers():
    text = "### Header 3\n## Header 2\n# Header 1"
    formatted = SlackFormatter.format(text)
    assert "*Header 3*" in formatted
    assert "*Header 2*" in formatted
    assert "*Header 1*" in formatted
