"""
Tests for CLI session fallback in _handle_list_dir() (api/routes.py).

PR #204: When a CLI session is selected in the UI, the /api/list endpoint
previously returned 404 because get_session() only checks WebUI in-memory
sessions. The fix adds a fallback to get_cli_sessions() for CLI sessions
not loaded in WebUI memory.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from api.routes import _handle_list_dir


def _make_handler(path_query):
    """Create a minimal mock handler for _handle_list_dir."""
    from urllib.parse import urlparse
    handler = MagicMock()
    handler.path = f'/api/list?{path_query}'
    handler.headers = {}
    # Capture what j() / bad() would send
    handler._response = None
    return handler


def _make_parsed(query_string):
    """Make a minimal parsed URL object with a query string."""
    from urllib.parse import urlparse
    return urlparse(f'http://localhost/api/list?{query_string}')


class MockSession:
    """Minimal WebUI session object with a workspace attribute."""
    def __init__(self, workspace):
        self.workspace = workspace


class TestCliSessionFileBrowserFallback(unittest.TestCase):
    """Unit tests for the CLI session fallback in _handle_list_dir."""

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.list_dir')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_cli_session_fallback_called_when_webui_session_not_found(
        self, mock_get_session, mock_get_cli_sessions, mock_list_dir,
        mock_bad, mock_j
    ):
        """When get_session raises KeyError, falls back to get_cli_sessions."""
        mock_get_session.side_effect = KeyError('not found')
        mock_get_cli_sessions.return_value = [
            {'session_id': 'cli-abc123', 'workspace': '/tmp/test-workspace'}
        ]
        mock_list_dir.return_value = []

        handler = MagicMock()
        parsed = _make_parsed('session_id=cli-abc123&path=.')
        _handle_list_dir(handler, parsed)

        mock_get_cli_sessions.assert_called_once()
        mock_list_dir.assert_called_once()
        mock_bad.assert_not_called()

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.list_dir')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_webui_session_used_directly_no_cli_fallback(
        self, mock_get_session, mock_get_cli_sessions, mock_list_dir,
        mock_bad, mock_j
    ):
        """When get_session succeeds, get_cli_sessions is never called."""
        mock_get_session.return_value = MockSession('/tmp/webui-workspace')
        mock_list_dir.return_value = []

        handler = MagicMock()
        parsed = _make_parsed('session_id=webui-sess-001&path=.')
        _handle_list_dir(handler, parsed)

        mock_get_cli_sessions.assert_not_called()
        mock_list_dir.assert_called_once()

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_cli_session_not_found_in_cli_sessions_returns_404(
        self, mock_get_session, mock_get_cli_sessions, mock_bad, mock_j
    ):
        """If the session_id is not in get_cli_sessions() either, returns 404."""
        mock_get_session.side_effect = KeyError('not found')
        mock_get_cli_sessions.return_value = []  # empty — session not found anywhere

        handler = MagicMock()
        parsed = _make_parsed('session_id=nonexistent-sess&path=.')
        _handle_list_dir(handler, parsed)

        mock_bad.assert_called_once()
        args = mock_bad.call_args
        # Should be a 404 error
        self.assertEqual(args[0][2], 404)

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_cli_session_missing_workspace_returns_400(
        self, mock_get_session, mock_get_cli_sessions, mock_bad, mock_j
    ):
        """CLI session with no workspace key returns a 400 error, not a crash."""
        mock_get_session.side_effect = KeyError('not found')
        mock_get_cli_sessions.return_value = [
            {'session_id': 'cli-no-ws'}  # no 'workspace' key
        ]

        handler = MagicMock()
        parsed = _make_parsed('session_id=cli-no-ws&path=.')
        _handle_list_dir(handler, parsed)

        # Should get a bad() call with 400 status, not a crash
        mock_bad.assert_called_once()
        args = mock_bad.call_args
        self.assertEqual(args[0][2], 400)

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_cli_session_empty_workspace_returns_400(
        self, mock_get_session, mock_get_cli_sessions, mock_bad, mock_j
    ):
        """CLI session with empty string workspace returns 400, not silent CWD traversal."""
        mock_get_session.side_effect = KeyError('not found')
        mock_get_cli_sessions.return_value = [
            {'session_id': 'cli-empty-ws', 'workspace': ''}
        ]

        handler = MagicMock()
        parsed = _make_parsed('session_id=cli-empty-ws&path=.')
        _handle_list_dir(handler, parsed)

        mock_bad.assert_called_once()
        args = mock_bad.call_args
        self.assertEqual(args[0][2], 400)

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_session_id_required(
        self, mock_get_session, mock_get_cli_sessions, mock_bad, mock_j
    ):
        """Missing session_id returns an error immediately."""
        handler = MagicMock()
        parsed = _make_parsed('path=.')  # no session_id
        _handle_list_dir(handler, parsed)

        mock_bad.assert_called_once()
        mock_get_session.assert_not_called()
        mock_get_cli_sessions.assert_not_called()

    @patch('api.routes.j')
    @patch('api.routes.bad')
    @patch('api.routes.list_dir')
    @patch('api.routes.get_cli_sessions')
    @patch('api.routes.get_session')
    def test_cli_session_none_workspace_returns_400(
        self, mock_get_session, mock_get_cli_sessions, mock_list_dir,
        mock_bad, mock_j
    ):
        """CLI session with workspace=None returns 400, not TypeError."""
        mock_get_session.side_effect = KeyError('not found')
        mock_get_cli_sessions.return_value = [
            {'session_id': 'cli-none-ws', 'workspace': None}
        ]

        handler = MagicMock()
        parsed = _make_parsed('session_id=cli-none-ws&path=.')
        _handle_list_dir(handler, parsed)

        # None workspace should be treated same as empty — return 400
        mock_bad.assert_called_once()
        mock_list_dir.assert_not_called()


if __name__ == '__main__':
    unittest.main()
