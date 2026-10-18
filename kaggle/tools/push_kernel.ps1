# Push + run a kernel. Usage: push_kernel.ps1 namma_pipeline
param([Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')

$dir = Join-Path $NammaRoot "kaggle\kernels\$Name"
if (-not (Test-Path $dir)) { throw "no such kernel dir: $dir" }
kaggle kernels push -p $dir
if ($LASTEXITCODE -ne 0) { throw "kernel push failed ($LASTEXITCODE)" }
$ref = "$NammaUser/" + ($Name -replace '_', '-')
Write-Host "pushed: $ref (check with: kaggle kernels status $ref)"
