param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ExternalToken = "test-token"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
& .\.venv\Scripts\python.exe scripts\smoke_e2e.py --base-url $BaseUrl --external-token $ExternalToken
