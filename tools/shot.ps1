# Headless screenshot of a URL (for abstract figures and demo stills).
# Usage: shot.ps1 -Url "http://127.0.0.1:5173/?capture=synthetic" -Out "docs\fig\viewer.png"
param(
    [string]$Url = 'http://127.0.0.1:5173/?capture=synthetic',
    [string]$Out = 'docs\fig\viewer.png',
    [string]$Size = '1600,1000',
    [int]$BudgetMs = 12000
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outPath = Join-Path $root $Out
New-Item -ItemType Directory -Force -Path (Split-Path $outPath) | Out-Null

$chromeCandidates = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw 'no Chrome/Edge found for headless screenshots' }

if (Test-Path $outPath) { Remove-Item $outPath -Force }
$oldPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
# chrome writes status to stderr; that is not a failure
& $chrome --headless=new --disable-gpu --hide-scrollbars `
    "--window-size=$Size" "--screenshot=$outPath" `
    "--virtual-time-budget=$BudgetMs" $Url 2>$null | Out-Null
$ErrorActionPreference = $oldPref
if (-not (Test-Path $outPath)) { throw 'screenshot was not produced' }
Write-Host ("shot: {0} ({1:N0} KB)" -f $outPath, ((Get-Item $outPath).Length / 1KB))
