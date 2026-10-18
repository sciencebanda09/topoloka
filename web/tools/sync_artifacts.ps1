# Sync fetched kernel artifacts into the web app's public folder.
# Usage: sync_artifacts.ps1 [-Kernel namma_pipeline] [-Capture house_v1]
param(
    [string]$Kernel = 'namma_pipeline',
    [string]$Capture = 'house_v1'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$src = Join-Path $root "kaggle\out\$Kernel"
$dst = Join-Path $root "web\public\artifacts\$Capture"
if (-not (Test-Path (Join-Path $src 'nav.json'))) {
    throw "nav.json not found in $src - run the kernel and fetch_output first"
}
New-Item -ItemType Directory -Force -Path $dst | Out-Null
$map = @{
    'nav.json'      = 'nav.json'
    'occupancy.png' = 'occupancy.png'
    'sparse.ply'    = 'cloud.ply'
    'splat.ply'     = 'splat.ply'
}
foreach ($k in $map.Keys) {
    $f = Join-Path $src $k
    if (Test-Path $f) {
        Copy-Item $f (Join-Path $dst $map[$k]) -Force
        Write-Host "synced $k -> $($map[$k])"
    }
}
Write-Host "artifacts in $dst"
