import subprocess
import sys
from pathlib import Path

import pytest

# The line glab-cli-extras prints when this package is installed next to it.
NOTICE = (
    "glab-pipeline: this package is deprecated; glab-cli-extras provides the same command."
    " Run: uv tool uninstall glab-pipeline && uv tool install glab-cli-extras"
)

# The console script in the project venv, next to the interpreter that runs the tests.
CONSOLE_SCRIPT = [str(Path(sys.executable).parent / "glab-pipeline")]
PYTHON_MODULE = [sys.executable, "-m", "glab_pipeline"]


def run(command: list[str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*command, *args], capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("command", [CONSOLE_SCRIPT, PYTHON_MODULE], ids=["console-script", "python-m"])
def test_help_prints_the_usage_on_stdout_and_the_notice_once_on_stderr(command: list[str]) -> None:
    result = run(command, "inspect", "--help")

    assert result.returncode == 0
    assert "--pipeline-url" in result.stdout
    assert "deprecated" not in result.stdout
    assert result.stderr.splitlines() == [NOTICE]


@pytest.mark.parametrize("command", [CONSOLE_SCRIPT, PYTHON_MODULE], ids=["console-script", "python-m"])
def test_a_usage_error_keeps_its_exit_code_and_prints_the_notice_once(command: list[str]) -> None:
    result = run(command, "inspect", "--no-such-option")

    assert result.returncode == 2
    assert result.stdout == ""
    stderr_lines = result.stderr.splitlines()
    assert stderr_lines.count(NOTICE) == 1
    assert "unrecognized arguments: --no-such-option" in result.stderr
