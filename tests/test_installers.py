from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_shell_installer_has_safe_dry_run():
    result = subprocess.run(["bash", str(ROOT / "install"), "--dry-run"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "-m venv" in result.stdout
    assert "pip install -e" in result.stdout


def test_powershell_installer_exists_and_is_non_secret():
    text = (ROOT / "install.ps1").read_text()
    assert "Python 3.11+" in text
    assert "pip install -e" in text
    assert "password" not in text.casefold()
    assert "token" not in text.casefold()
