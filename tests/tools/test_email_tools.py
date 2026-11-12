"""
Unit tests for Victor 2.0 Email tools.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.tools.email.tool import (
    EmailGetUnreadSummaryTool,
    EmailSearchMessagesTool,
    _decode_header_value,
    _extract_text_body,
    _get_imap_connection,
    _parse_date,
    _wrap_untrusted,
)


def test_security_boundary_wrapping():
    wrapped = _wrap_untrusted("Hello world")
    assert "Hello world" in wrapped
    assert "SYSTEM SECURITY WARNING" in wrapped


def test_decode_header_and_parse_date():
    assert _decode_header_value(None) == "(unknown)"
    assert _decode_header_value("Plain Subject") == "Plain Subject"
    assert _parse_date(None) == "(unknown date)"


def test_get_imap_connection_missing_credentials(monkeypatch):
    monkeypatch.delenv("EMAIL_USER", raising=False)
    monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="Email credentials not configured"):
        _get_imap_connection()


def test_get_imap_connection_strips_spaces(monkeypatch):
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")

    with patch("imaplib.IMAP4_SSL") as mock_imap:
        mock_instance = MagicMock()
        mock_imap.return_value = mock_instance

        _get_imap_connection()

        mock_instance.login.assert_called_once_with("user@example.com", "abcdefghijklmnop")


@pytest.mark.asyncio
async def test_email_get_unread_summary_no_emails():
    tool = EmailGetUnreadSummaryTool()

    with patch("app.tools.email.tool._get_imap_connection") as mock_conn_fn:
        mock_conn = MagicMock()
        mock_conn.search.return_value = ("OK", [b""])
        mock_conn_fn.return_value = mock_conn

        res = await tool.execute({})
        assert "no unread emails" in res.lower()


@pytest.mark.asyncio
async def test_email_search_messages_empty_query():
    tool = EmailSearchMessagesTool()
    res = await tool.execute({"query": "  "})
    assert "provide a search query" in res.lower()
