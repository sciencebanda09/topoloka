# Wait for a kernel (optional) and download its outputs.
# Usage: fetch_output.ps1 namma_pipeline [-Watch]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [switch]$Watch,
    [int]$TimeoutMinutes = 60
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')

# The kaggle CLI prints unicode (the kernel log contains em-dashes etc.) and
# Windows PowerShell hands Python a cp1252 stdout: it dies with a 'charmap'
# codec error and leaves a 0-byte log. Force UTF-8 for all child processes.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$ref = "$NammaUser/" + ($Name -replace '_', '-')

if ($Watch) {
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        # A transient CLI/network hiccup must not kill the watcher: the CLI
        # prints python errors (connection resets etc.) to stderr, which
        # EAP=Stop would turn into a terminating error.
        $ErrorActionPreference = 'Continue'
        try {
            $status = (kaggle kernels status $ref 2>&1 | Out-String)
        } catch {
            $status = "watch: status check threw: $($_.Exception.Message)"
        }
        $ErrorActionPreference = 'Stop'
        # status text is like: <ref> has status "KernelWorkerStatus.COMPLETE"
        if ($status -match 'COMPLETE') { Write-Host 'kernel complete'; break }
        if ($status -match 'ERROR|CANCELLED') {
            # still download whatever was produced: summaries/logs explain the failure
            Write-Host "kernel ended with: $($status.Trim())"
            break
        }
        Start-Sleep -Seconds 30
    }
}

$outDir = Join-Path $NammaRoot "kaggle\out\$Name"
Remove-Item -Recurse -Force $outDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Retry: a single CLI hiccup (network, unicode console bug) must not cost a
# completed kernel run. Re-runs resume: up-to-date files are skipped.
$ok = $false
for ($i = 1; $i -le 3; $i++) {
    $ErrorActionPreference = 'Continue'   # CLI stderr is not a terminating error
    kaggle kernels output $ref -p $outDir
    $rc = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($rc -eq 0) { $ok = $true; break }
    Write-Host "fetch attempt $i failed (rc=$rc); retrying in 20 s"
    Start-Sleep -Seconds 20
}
if (-not $ok) { throw "output fetch failed after 3 attempts" }

$summary = Join-Path $outDir 'out\summary.txt'
if (Test-Path $summary) {
    Write-Host "---- summary.txt ----"
    Get-Content $summary
}
Get-ChildItem -Recurse $outDir | Select-Object FullName, Length
