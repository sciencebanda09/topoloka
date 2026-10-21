# Sync fetched kernel artifacts into the web app's public folder.
# Usage: sync_artifacts.ps1 [-Kernel namma_pipeline] [-Capture house_v1]
param(
    [string]$Kernel = 'namma_pipeline',
    [string]$Capture = 'house_v1'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$base = Join-Path $root "kaggle\out\$Kernel"
# fetch_output mirrors /kaggle/working: outputs live under out/web; older
# fetches (and the CPU kernel) may have landed web/ at the top level.
$candidates = @((Join-Path $base 'out\web'), (Join-Path $base 'web'))
$src = $candidates | Where-Object { Test-Path (Join-Path $_ 'nav.json') } | Select-Object -First 1
if (-not $src) {
    throw "no web bundle under $base (looked in out/web and web) - run the kernel and fetch_output first"
}
$dst = Join-Path $root "web\public\artifacts\$Capture"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $src '*') $dst -Force -Recurse
Get-ChildItem $dst | ForEach-Object {
    Write-Host ("synced {0} ({1:N0} bytes)" -f $_.Name, $_.Length)
}
Write-Host "artifacts in $dst"
