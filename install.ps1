param([switch]$DryRun, [string]$Python = "python", [string]$Venv = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Venv) { $Venv = Join-Path $Root ".venv" }
if ($DryRun) {
  Write-Output "$Python -m venv $Venv"
  Write-Output "$Venv\Scripts\python.exe -m pip install -e $Root"
  exit 0
}
& $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required" }
& $Python -m venv $Venv
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e $Root
Write-Output "Installed. Run: $Venv\Scripts\agentic-data-platform.exe doctor"
