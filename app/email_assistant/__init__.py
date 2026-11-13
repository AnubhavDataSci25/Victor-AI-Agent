"""
Victor Autonomous Email Assistant & Management System.
"""

from app.email_assistant.manager import EmailAssistantManager
from app.email_assistant.tools import get_email_assistant_manager

__all__ = ["EmailAssistantManager", "get_email_assistant_manager"]
