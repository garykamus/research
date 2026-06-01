# Build script for Release Orchestration Dashboard (Windows)
# Usage: .\packaging\build.ps1 [-Clean]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

if ($Clean) {
    Write-Host "Cleaning previous build artefacts..."
    Remove-Item "$root\dist" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "$root\build\pyinstaller" -Recurse -Force -ErrorAction SilentlyContinue
}

Set-Location $root
Write-Host "Building ReleaseOrchestration.exe..."
pyinstaller packaging\app.spec --distpath dist --workpath build\pyinstaller --noconfirm

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Build complete: $root\dist\ReleaseOrchestration.exe"
} else {
    Write-Host "Build FAILED (exit code $LASTEXITCODE)"
    exit $LASTEXITCODE
}
