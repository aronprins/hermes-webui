"""
Tests for branch-aware update checker (api/updates.py).

Verifies that _check_repo() uses the current branch's upstream tracking ref
rather than always comparing against origin/master.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from api.updates import _check_repo, _apply_update_inner


def _run_git_mock(args, path, timeout=None):
    """Default mock: nothing behind, no upstream, clean state."""
    cmd = ' '.join(args)
    if 'rev-parse' in cmd and '@{upstream}' in cmd:
        return ('', False)  # no upstream set
    if 'rev-parse' in cmd and 'abbrev-ref' in cmd and 'HEAD' in cmd:
        return ('main', True)
    if 'rev-list' in cmd and 'count' in cmd:
        return ('0', True)
    if 'rev-parse' in cmd and 'short' in cmd:
        return ('abc1234', True)
    if 'status' in cmd:
        return ('', True)
    return ('', True)


class TestUpdateCheckerBranchAware(unittest.TestCase):
    """Test that _check_repo respects the branch's upstream tracking ref."""

    @patch('api.updates._run_git')
    def test_uses_default_branch_when_no_upstream(self, mock_run):
        """When @{upstream} is not set, falls back to origin/<default_branch>."""
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if '@{upstream}' in cmd:
                return ('', False)  # no upstream
            if 'symbolic-ref' in cmd or ('rev-parse' in cmd and 'abbrev-ref' in cmd and 'HEAD' not in cmd):
                return ('main', True)  # default branch
            if 'rev-list' in cmd and 'count' in cmd:
                return ('0', True)
            if 'rev-parse' in cmd and 'short' in cmd:
                return ('abc1234', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _check_repo(ROOT, 'webui')

        # Should use origin/main as compare_ref
        calls = [str(c) for c in mock_run.call_args_list]
        rev_list_call = next((c for c in calls if 'rev-list' in c and 'count' in c), None)
        self.assertIsNotNone(rev_list_call)
        self.assertIn('origin/main', rev_list_call)

    @patch('api.updates._run_git')
    def test_uses_upstream_when_set(self, mock_run):
        """When @{upstream} is set, uses it for the compare ref."""
        upstream_ref = 'origin/feat/my-feature'

        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if '@{upstream}' in cmd:
                return (upstream_ref, True)  # upstream set
            if 'rev-list' in cmd and 'count' in cmd:
                return ('3', True)  # 3 commits behind
            if 'rev-parse' in cmd and 'short' in cmd:
                return ('deadbeef', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _check_repo(ROOT, 'webui')

        # Should use the upstream ref, not origin/master
        calls = [str(c) for c in mock_run.call_args_list]
        rev_list_call = next((c for c in calls if 'rev-list' in c and 'count' in c), None)
        self.assertIsNotNone(rev_list_call)
        self.assertIn(upstream_ref, rev_list_call)
        # Must NOT use origin/master when upstream is set
        self.assertNotIn('origin/master', rev_list_call)
        self.assertNotIn('origin/main', rev_list_call)

    @patch('api.updates._run_git')
    def test_behind_count_reflected_in_result(self, mock_run):
        """The behind count from compare_ref is returned correctly."""
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if '@{upstream}' in cmd:
                return ('origin/master', True)
            if 'rev-list' in cmd and 'count' in cmd:
                return ('7', True)
            if 'rev-parse' in cmd and 'short' in cmd:
                return ('feedc0de', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _check_repo(ROOT, 'agent')

        self.assertEqual(result['behind'], 7)
        self.assertEqual(result['latest_sha'], 'feedc0de')

    @patch('api.updates._run_git')
    def test_apply_update_uses_plain_ff_only_pull(self, mock_run):
        """_apply_update_inner must call git pull --ff-only with no extra args.

        The old bug: it passed compare_ref as an arg to pull, e.g.:
          git pull --ff-only origin/feat/foo
        Git interprets that as a remote name, not a refspec, and fails with:
          fatal: 'origin/feat/foo' does not appear to be a git repository

        The fix: git pull --ff-only (no args). Git uses the configured @{upstream}.
        """
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if 'status' in cmd:
                return ('', True)  # nothing to stash
            if '@{upstream}' in cmd:
                return ('origin/master', True)
            if 'pull' in cmd:
                return ('Already up to date.', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _apply_update_inner('webui')

        # Find the pull call
        pull_calls = [c for c in mock_run.call_args_list
                      if c.args and 'pull' in c.args[0]]
        self.assertEqual(len(pull_calls), 1, f"Expected exactly one pull call, got: {pull_calls}")

        pull_args = pull_calls[0].args[0]
        self.assertIn('pull', pull_args)
        self.assertIn('--ff-only', pull_args)
        # The pull call must NOT include any compare_ref (e.g. 'origin/master')
        # because passing it as a positional arg makes git treat it as a remote name
        extra_args = [a for a in pull_args if a not in ('git', 'pull', '--ff-only')]
        self.assertEqual(extra_args, [], f"pull call should have no extra args, got: {extra_args}")

    @patch('api.updates._run_git')
    def test_no_upstream_fallback_also_uses_plain_pull(self, mock_run):
        """Even when @{upstream} is not set, the pull still uses no extra args."""
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if 'status' in cmd:
                return ('', True)
            if '@{upstream}' in cmd:
                return ('', False)  # no upstream
            if 'symbolic-ref' in cmd or ('rev-parse' in cmd and 'abbrev-ref' in cmd):
                return ('main', True)
            if 'pull' in cmd:
                return ('Already up to date.', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _apply_update_inner('webui')

        pull_calls = [c for c in mock_run.call_args_list
                      if c.args and 'pull' in c.args[0]]
        self.assertGreaterEqual(len(pull_calls), 1)
        pull_args = pull_calls[0].args[0]
        extra_args = [a for a in pull_args if a not in ('git', 'pull', '--ff-only')]
        self.assertEqual(extra_args, [], f"pull call should have no extra args, got: {extra_args}")


class TestUpdateCheckerResultFormat(unittest.TestCase):
    """Verify the result dict structure from _check_repo."""

    @patch('api.updates._run_git')
    def test_result_has_required_keys(self, mock_run):
        """_check_repo always returns a dict with ok, name, behind, latest, branch."""
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if '@{upstream}' in cmd:
                return ('origin/master', True)
            if 'rev-list' in cmd and 'count' in cmd:
                return ('0', True)
            if 'rev-parse' in cmd and 'short' in cmd:
                return ('abc0000', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _check_repo(ROOT, 'webui')

        self.assertIn('name', result)
        self.assertIn('behind', result)
        self.assertIn('latest_sha', result)
        self.assertIn('branch', result)
        self.assertEqual(result['name'], 'webui')

    @patch('api.updates._run_git')
    def test_result_behind_zero_on_rev_list_failure(self, mock_run):
        """If rev-list fails (non-digit output), behind defaults to 0."""
        def side_effect(args, path, timeout=None):
            cmd = ' '.join(str(a) for a in args)
            if '@{upstream}' in cmd:
                return ('origin/master', True)
            if 'rev-list' in cmd and 'count' in cmd:
                return ('', False)  # simulate failure - returns empty string
            if 'rev-parse' in cmd and 'short' in cmd:
                return ('abc0000', True)
            return ('', True)

        mock_run.side_effect = side_effect
        result = _check_repo(ROOT, 'webui')

        # When rev-list fails, behind defaults to 0 (not a crash)
        self.assertIsNotNone(result)
        self.assertEqual(result['behind'], 0)


if __name__ == '__main__':
    unittest.main()
