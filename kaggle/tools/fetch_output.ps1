# Wait for a kernel (optional) and download its outputs.
# Usage: fetch_output.ps1 namma_pipeline [-Watch]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [switch]$Watch,
    [int]$TimeoutMinutes = 60
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')

$ref = "$NammaUser/" + ($Name -replace '_', '-')

if ($Watch) {
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        $status = (kaggle kernels status $ref 2>&1 | Out-String)
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
kaggle kernels output $ref -p $outDir
if ($LASTEXITCODE -ne 0) { throw "output fetch failed ($LASTEXITCODE)" }
Get-ChildItem -Recurse $outDir | Select-Object FullName, Length
