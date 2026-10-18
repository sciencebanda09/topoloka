# Stage the local pipeline/ source and push it as the namma-code Kaggle dataset.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')

$staging = Join-Path $NammaRoot 'kaggle\staging'
$src     = Join-Path $staging 'src'
$upload  = Join-Path $staging 'upload'

Remove-Item -Recurse -Force $src, $upload -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $src, $upload | Out-Null

Write-Host "staging pipeline source..."
robocopy (Join-Path $NammaRoot 'pipeline') $src /E /XD runs __pycache__ /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

$tar = Join-Path $upload 'code.tar'
tar -cf $tar -C $src .
if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
Write-Host ("code.tar: {0:N0} bytes" -f (Get-Item $tar).Length)

Copy-Item (Join-Path $NammaRoot 'kaggle\datasets\namma-code\dataset-metadata.json') `
          (Join-Path $upload 'dataset-metadata.json') -Force

$oldPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'   # native stderr must not terminate the script
kaggle datasets files $CodeDataset 1>$null 2>$null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $oldPref

if ($exists) {
    Write-Host "dataset exists -> new version"
    kaggle datasets version -p $upload -m "code sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
} else {
    Write-Host "dataset missing -> create"
    kaggle datasets create -p $upload
}
if ($LASTEXITCODE -ne 0) { throw "kaggle dataset upload failed ($LASTEXITCODE)" }
Write-Host "namma-code synced."
