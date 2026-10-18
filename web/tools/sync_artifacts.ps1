# Sync fetched kernel artifacts into the web app's public folder.
# Usage: sync_artifacts.ps1 [-Kernel namma_pipeline] [-Capture house_v1]
param(
    [string]$Kernel = 'namma_pipeline',
    [string]$Capture = 'house_v1'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$src = Join-Path $root "kaggle\out\$Kernel\web"
$dst = Join-Path $root "web\public\artifacts\$Capture"
if (-not (Test-Path (Join-Path $src 'nav.json'))) {
    throw "no web bundle in $src - run the kernel and fetch_output first"
}
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $src '*') $dst -Force -Recurse
Get-ChildItem $dst | ForEach-Object {
    Write-Host ("synced {0} ({1:N0} bytes)" -f $_.Name, $_.Length)
}
Write-Host "artifacts in $dst"
