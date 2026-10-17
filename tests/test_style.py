# the coding standard (PEP 8, configured in pyproject.toml) is part of the test suite,
# so code that doesn't follow it fails `uv run pytest`
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ruff(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ruff", *args], cwd=ROOT, capture_output=True, text=True)


def test_code_passes_lint():
    result = ruff("check", ".")
    assert result.returncode == 0, result.stdout


def test_code_is_formatted():
    result = ruff("format", "--check", ".")
    assert result.returncode == 0, result.stdout
