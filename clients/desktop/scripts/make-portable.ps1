param(
    [string]$Version = "0.7.0",
    [string]$ServerUrl = $env:SOLO_SERVER_URL
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $Root "dist\win-unpacked"
$ReleaseDir = Join-Path $Root "release"
$Archive = Join-Path $ReleaseDir "SoloRecord-$Version-windows-x64.zip"

if (!(Test-Path -LiteralPath (Join-Path $AppDir "SoloRecord.exe"))) {
    throw "Run npm run pack or electron-builder first; $AppDir is missing SoloRecord.exe."
}

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
if ($ServerUrl) {
    $ServerUrl.Trim() | Set-Content -LiteralPath (Join-Path $AppDir "server-url.txt") -Encoding ascii
} else {
    $configPath = Join-Path $AppDir "server-url.txt"
    if (Test-Path -LiteralPath $configPath) {
        Remove-Item -LiteralPath $configPath -Force
    }
}
if (Test-Path -LiteralPath $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}

Compress-Archive -Path (Join-Path $AppDir "*") -DestinationPath $Archive -CompressionLevel Optimal
Write-Host $Archive
