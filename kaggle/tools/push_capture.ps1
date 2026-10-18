# Build/refresh the namma-capture-v1 dataset from fetched pipeline outputs.
# The splat kernel trains on it. Run after fetch_output.ps1 namma_pipeline.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')

$src = Join-Path $NammaRoot 'kaggle\out\namma_pipeline\out'
$stage = Join-Path $NammaRoot 'kaggle\staging\capture'
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

foreach ($f in @('frames.zip', 'transforms.json', 'sparse.ply', 'poses.json', 'sparse_txt.zip')) {
    $p = Join-Path $src $f
    if (-not (Test-Path $p)) { throw "missing $f in $src (run the pipeline kernel + fetch first)" }
    Copy-Item $p $stage -Force
}

$meta = @'
{
  "title": "Namma Capture V1",
  "id": "shashankdev09/namma-capture-v1",
  "licenses": [{"name": "other"}]
}
'@
# NB: Set-Content -Encoding UTF8 writes a BOM in Windows PowerShell 5.1,
# which breaks the Kaggle CLI's JSON parser -- write raw UTF-8 without BOM.
[System.IO.File]::WriteAllText((Join-Path $stage 'dataset-metadata.json'), $meta,
    (New-Object System.Text.UTF8Encoding($false)))

$dataset = "$NammaUser/namma-capture-v1"
$oldPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
kaggle datasets files $dataset 1>$null 2>$null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $oldPref

if ($exists) {
    kaggle datasets version -p $stage -m "capture sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
} else {
    kaggle datasets create -p $stage
}
if ($LASTEXITCODE -ne 0) { throw "capture dataset upload failed ($LASTEXITCODE)" }
Write-Host "namma-capture-v1 synced."
