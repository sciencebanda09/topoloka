# Render a markdown doc to PDF: pandoc (md -> styled html) + Chrome headless (html -> pdf).
# Usage: build_pdf.ps1 [-Doc docs\abstract.md] [-Output docs\abstract.pdf]
param(
    [string]$Doc = 'docs\abstract.md',
    [string]$Output = 'docs\abstract.pdf'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$inPath = Join-Path $root $Doc
$outPath = Join-Path $root $Output
$css = Join-Path $root 'docs\abstract.css'
$html = Join-Path $env:TEMP 'topoloka_doc.html'

if (-not (Test-Path $inPath)) { throw "input not found: $inPath" }
$docDir = Split-Path $inPath -Parent
pandoc $inPath -f gfm -t html5 -s -c $css --embed-resources --resource-path="$docDir" -o $html
if ($LASTEXITCODE -ne 0) { throw "pandoc failed ($LASTEXITCODE)" }

$chromeCandidates = @(
    'C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw 'no Chrome/Edge found for PDF printing' }

$uri = 'file:///' + ($html -replace '\\', '/')
$oldPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
# chrome writes the "bytes written" status line to stderr; that is not a failure
& $chrome --headless=new --disable-gpu --no-pdf-header-footer `
    --virtual-time-budget=3000 "--print-to-pdf=$outPath" $uri 2>$null | Out-Null
$ErrorActionPreference = $oldPref
if (-not (Test-Path $outPath)) { throw 'PDF was not produced' }

$bytes = [System.IO.File]::ReadAllBytes($outPath)
$text = [System.Text.Encoding]::ASCII.GetString($bytes)
$pages = ''
if ($text -match '/Count\s+(\d+)') { $pages = "$($Matches[1]) pages" }
Write-Host ("PDF: {0} ({1:N0} KB{2})" -f $outPath, ($bytes.Length / 1KB), $(if ($pages) { ", $pages" } else { '' }))
