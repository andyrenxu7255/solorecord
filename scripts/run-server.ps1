$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r server\requirements.txt

$env:PYTHONPATH = "$Root\server"
& .\.venv\Scripts\python.exe server\run_dev.py
