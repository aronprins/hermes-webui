from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess
from api.startup import auto_install_agent_deps

class TestAutoInstallAgentDeps:
    def test_installs_from_requirements_txt(self, tmp_path):
        agent_dir = tmp_path / 'hermes-agent'
        agent_dir.mkdir()
        req = agent_dir / 'requirements.txt'
        req.write_text('pyyaml\n')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr='')
            assert auto_install_agent_deps(agent_dir=agent_dir) is True
            args = mock_run.call_args[0][0]
            assert '-r' in args and str(req) in args

    def test_falls_back_to_pyproject(self, tmp_path):
        agent_dir = tmp_path / 'hermes-agent'
        agent_dir.mkdir()
        (agent_dir / 'pyproject.toml').write_text('[project]\nname="hermes-agent"\n')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr='')
            assert auto_install_agent_deps(agent_dir=agent_dir) is True
            args = mock_run.call_args[0][0]
            assert str(agent_dir) in args and '-r' not in args

    def test_skips_when_agent_dir_missing(self, capsys):
        with patch('subprocess.run') as mock_run:
            assert auto_install_agent_deps(agent_dir=None) is False
            assert not mock_run.called
        assert 'skipped' in capsys.readouterr().out.lower()

    def test_skips_when_no_install_file(self, tmp_path, capsys):
        agent_dir = tmp_path / 'hermes-agent'
        agent_dir.mkdir()
        with patch('subprocess.run') as mock_run:
            assert auto_install_agent_deps(agent_dir=agent_dir) is False
            assert not mock_run.called
        assert 'skipped' in capsys.readouterr().out.lower()

    def test_tolerates_pip_failure(self, tmp_path, capsys):
        agent_dir = tmp_path / 'hermes-agent'
        agent_dir.mkdir()
        (agent_dir / 'requirements.txt').write_text('somepkg\n')
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr='ERROR: could not find package')
            assert auto_install_agent_deps(agent_dir=agent_dir) is False
        out = capsys.readouterr().out.lower()
        assert 'failed' in out

    def test_tolerates_timeout(self, tmp_path, capsys):
        agent_dir = tmp_path / 'hermes-agent'
        agent_dir.mkdir()
        (agent_dir / 'requirements.txt').write_text('somepkg\n')
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('pip', 120)):
            assert auto_install_agent_deps(agent_dir=agent_dir) is False
        assert 'timed out' in capsys.readouterr().out.lower()
