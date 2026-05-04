import os
import tempfile
from unittest.mock import patch
from pathlib import Path
from tools.setup_wizard import SetupWizard

def test_setup_wizard_generates_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        
        # 1. Mock inputs to simulate user typing
        # Let's say user chooses:
        # - backend: gemini
        # - GEMINI_API_KEY: AIzaSy...
        # - default options for others
        mock_inputs = [
            "gemini",       # LLM_BACKEND
            "AIzaSy12345",  # GEMINI_API_KEY
            "n",            # Slack integration (n)
            "n",            # Notion integration (n)
            "",             # ADMIN_API_KEY (will auto-generate)
            "",             # CLIENT_API_KEY (will auto-generate)
            "",             # DISPATCH_HMAC_SECRET (will auto-generate)
            "",             # ENCRYPTION_KEY (will auto-generate)
            "",             # REDIS_ORCHESTRA_PASSWORD (will auto-generate)
            "",             # REDIS_COMMUNITY_PASSWORD (will auto-generate)
        ]
        
        wizard = SetupWizard(env_path=env_path)
        
        with patch('builtins.input', side_effect=mock_inputs):
            wizard.run()
            
        assert env_path.exists()
        
        content = env_path.read_text(encoding="utf-8")
        
        assert "LLM_BACKEND=gemini" in content
        assert "GEMINI_API_KEY=AIzaSy12345" in content
        assert "ADMIN_API_KEY=" in content # It shouldn't be empty, it should have a generated value
        
        # Parse env file to a dict
        env_dict = {}
        for line in content.splitlines():
            if line.strip() and not line.startswith('#'):
                key, val = line.split('=', 1)
                env_dict[key.strip()] = val.strip()
                
        assert "ADMIN_API_KEY" in env_dict
        assert len(env_dict["ADMIN_API_KEY"]) >= 32
        
        assert "CLIENT_API_KEY" in env_dict
        assert len(env_dict["CLIENT_API_KEY"]) >= 32
        
        assert "DISPATCH_HMAC_SECRET" in env_dict
        assert len(env_dict["DISPATCH_HMAC_SECRET"]) >= 32
        
        assert "ENCRYPTION_KEY" in env_dict
        assert len(env_dict["ENCRYPTION_KEY"]) >= 32
        
        assert "REDIS_ORCHESTRA_PASSWORD" in env_dict
        assert len(env_dict["REDIS_ORCHESTRA_PASSWORD"]) >= 16

def test_setup_wizard_claude_backend():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        
        mock_inputs = [
            "claude",       # LLM_BACKEND
            "sk-ant-12345", # ANTHROPIC_API_KEY
            "n",            # Slack integration (n)
            "n",            # Notion integration (n)
            "",             # ADMIN_API_KEY 
            "",             # CLIENT_API_KEY 
            "",             # DISPATCH_HMAC_SECRET 
            "",             # ENCRYPTION_KEY 
            "",             # REDIS_ORCHESTRA_PASSWORD 
            "",             # REDIS_COMMUNITY_PASSWORD 
        ]
        
        wizard = SetupWizard(env_path=env_path)
        
        with patch('builtins.input', side_effect=mock_inputs):
            wizard.run()
            
        content = env_path.read_text(encoding="utf-8")
        assert "LLM_BACKEND=claude" in content
        assert "ANTHROPIC_API_KEY=sk-ant-12345" in content

def test_setup_wizard_slack_notion():
    with tempfile.TemporaryDirectory() as tmpdir:
        env_path = Path(tmpdir) / ".env"
        
        mock_inputs = [
            "gemini",
            "AIzaSy12345",
            "y",            # Slack integration (y)
            "xoxb-123",     # SLACK_BOT_TOKEN
            "xapp-123",     # SLACK_APP_TOKEN
            "C123",         # SLACK_CHANNEL
            "y",            # Notion integration (y)
            "ntn_123",      # NOTION_TOKEN
            "db_123",       # NOTION_DATABASE_ID
            "",             # ADMIN_API_KEY
            "",             # CLIENT_API_KEY
            "",             # DISPATCH_HMAC_SECRET
            "",             # ENCRYPTION_KEY
            "",             # REDIS_ORCHESTRA_PASSWORD
            "",             # REDIS_COMMUNITY_PASSWORD
        ]
        
        wizard = SetupWizard(env_path=env_path)
        
        with patch('builtins.input', side_effect=mock_inputs):
            wizard.run()
            
        content = env_path.read_text(encoding="utf-8")
        assert "SLACK_BOT_TOKEN=xoxb-123" in content
        assert "SLACK_APP_TOKEN=xapp-123" in content
        assert "SLACK_CHANNEL=C123" in content
        assert "NOTION_TOKEN=ntn_123" in content
        assert "NOTION_DATABASE_ID=db_123" in content
