import pytest
from agents.communication_agent.slack.message_cleaner import MessageCleaner

def test_clean_user_mention():
    text = "<@U12345> hello"
    assert MessageCleaner.clean(text) == "hello"

def test_clean_channel_mention():
    text = "<#C12345|general> check this"
    assert MessageCleaner.clean(text) == "check this"

def test_clean_special_mention():
    assert MessageCleaner.clean("<!here> attention") == "attention"
    assert MessageCleaner.clean("<!channel> everyone") == "everyone"

def test_clean_link_with_text():
    text = "go to <https://example.com|website>"
    assert MessageCleaner.clean(text) == "go to website"

def test_clean_link_without_text():
    text = "check <https://example.com>"
    assert MessageCleaner.clean(text) == "check"

def test_html_entities():
    text = "A &amp; B &lt; C"
    assert MessageCleaner.clean(text) == "A & B < C"

def test_mixed_content():
    text = "<@U123> <#C456|dev> <!here> look at <https://example.com|this> &amp; <https://google.com>"
    assert MessageCleaner.clean(text) == "look at this &"
