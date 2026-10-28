# Upload one raw phone video (mp4/mov/webm/...) and run the CPU pipeline on it.
#
# This is the live-capture entry point: the phone records, this script turns the
# file into a Kaggle dataset, generates a pipeline kernel that mounts it, and
# (with -Splat) chains the GPU splat stage afterwards.
#
# Usage:
#   powershell -File kaggle\tools\push_video.ps1 -Video C:\capture\room.mov -Name room_v1
#   powershell -File kaggle\tools\push_video.ps1 -Video ... -Name room_v1 -Splat
#
# Defaults: upload + push the CPU pipeline. -Watch fetches its output.
# -Splat implies -Watch and then runs the capture/splat stages too.
param(
    [Parameter(Mandatory = $true)][string]$Video,
    [string]$Name = '',
    [string]$Title = '',
    [switch]$Watch,
    [switch]$Splat,
    [switch]$DryRun,
    [switch]$AllowPortrait,
    [int]$TimeoutMinutes = 180
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\config.ps1')
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

function Wait-DatasetReady([string]$Dataset, [int]$Minutes = 20) {
    Write-Host "waiting for $Dataset to be ready..."
    $deadline = (Get-Date).AddMinutes($Minutes)
    $last = ''
    while ((Get-Date) -lt $deadline) {
        $ErrorActionPreference = 'Continue'
        $last = (kaggle datasets status $Dataset 2>&1 | Out-String).Trim()
        $ErrorActionPreference = 'Stop'
        if ($last -match '\bready\b') { Write-Host "dataset ready: $Dataset"; return }
        Start-Sleep -Seconds 15
    }
    throw "$Dataset did not become ready in $Minutes min (last: $last)"
}

$Video = (Resolve-Path $Video).Path
if (-not (Test-Path $Video -PathType Leaf)) { throw "video not found: $Video" }
$ext = [IO.Path]::GetExtension($Video).ToLowerInvariant()
$allowed = @('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi')
if ($allowed -notcontains $ext) {
    throw "unsupported video extension '$ext' (expected one of $($allowed -join ', '))"
}
$sizeMb = [math]::Round((Get-Item $Video).Length / 1MB, 1)
if ($sizeMb -lt 5) { Write-Host "WARNING: only $sizeMb MB; a 90 s capture should be much larger" }

if (-not $Name) { $Name = [IO.Path]::GetFileNameWithoutExtension($Video) }
$slug = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
if ($slug.Length -lt 3 -or $slug.Length -gt 30) {
    throw "capture name must produce a 3-30 char slug (got '$slug'); prefixes like namma-capture- count against Kaggle's slug limit"
}
if (-not $Title) { $Title = "Namma $slug video" }

$videoDataset = "$NammaUser/namma-$slug-video"
$captureDataset = "$NammaUser/namma-capture-$slug"
$kernelName = 'namma_pipeline_' + ($slug -replace '-', '_')
$kernelRef = "$NammaUser/namma-pipeline-$slug"
$splatName = 'namma_splat_' + ($slug -replace '-', '_')
$splatRef = "$NammaUser/namma-splat-$slug"

# ---- 0. preflight: fail before a 2.5 h Kaggle round-trip -------------------
$ffprobe = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffprobe.exe"
if (-not (Test-Path $ffprobe)) {
    $cmd = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($cmd) { $ffprobe = $cmd.Source }
}
if ($ffprobe -and (Test-Path $ffprobe)) {
    $ErrorActionPreference = 'Continue'
    $raw = (& $ffprobe -v error -select_streams v:0 `
        -show_entries stream=width,height,avg_frame_rate,codec_name:format=duration `
        -of json $Video 2>$null | Out-String)
    $ErrorActionPreference = 'Stop'
    try {
        $info = $raw | ConvertFrom-Json
        $st = $info.streams[0]
        $w = [int]$st.width
        $h = [int]$st.height
        $dur = 0.0
        [void][double]::TryParse([string]$info.format.duration, [ref]$dur)
        $fps = 0.0
        if ($st.avg_frame_rate -match '^(\d+)/(\d+)$' -and [int]$Matches[2] -gt 0) {
            $fps = [double]$Matches[1] / [double]$Matches[2]
        }
        Write-Host ("probe    {0}x{1}, {2:N1} fps, {3:N1} s, {4}" -f $w, $h, $fps, $dur, $st.codec_name)
        if ($h -gt $w -and -not $AllowPortrait) {
            throw "portrait video ($w x $h); the SOP requires landscape. Re-record landscape, or pass -AllowPortrait to override."
        }
        if ($dur -gt 0 -and $dur -lt 45) { Write-Host "WARNING: $([math]::Round($dur,1)) s is short; a single room needs ~90 s" }
        if ($dur -gt 300) { Write-Host "WARNING: $([math]::Round($dur,1)) s is long; upload and CPU time grow" }
        if ($w -gt 0 -and $w -lt 1280) { Write-Host "WARNING: width $w; 1080p is the floor, 4K preferred" }
        if ($fps -gt 0 -and $fps -lt 24) { Write-Host "WARNING: $([math]::Round($fps,1)) fps; use 30 fps" }
    } catch {
        if ($_.Exception.Message -like '*portrait video*') { throw }
        Write-Host "probe failed; continuing without preflight details"
    }
} else {
    Write-Host "probe skipped (ffprobe not found)"
}

Write-Host "video    $Video ($sizeMb MB)"
Write-Host "dataset  $videoDataset"
Write-Host "kernel   $kernelRef"
if ($Splat) { Write-Host "splat    $splatRef (after CPU stage)" }
if ($DryRun) {
    Write-Host "dry run: would upload + push the kernels; no Kaggle calls made"
    return
}

# ---- 1. upload the raw video as a dataset ---------------------------------
$stage = Join-Path $NammaRoot "kaggle\staging\video_$($slug -replace '-', '_')"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $Video (Join-Path $stage ("source" + $ext)) -Force

$meta = @"
{
  "title": "$Title",
  "id": "$videoDataset",
  "licenses": [{"name": "other"}]
}
"@
# No BOM: Windows PowerShell 5.1's Set-Content UTF8 writes one and the CLI
# rejects the metadata JSON.
[System.IO.File]::WriteAllText((Join-Path $stage 'dataset-metadata.json'), $meta,
    (New-Object System.Text.UTF8Encoding($false)))

$oldPref = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
kaggle datasets files $videoDataset 1>$null 2>$null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $oldPref

if ($exists) {
    kaggle datasets version -p $stage -m "phone capture $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
} else {
    kaggle datasets create -p $stage
}
if ($LASTEXITCODE -ne 0) { throw "video dataset upload failed ($LASTEXITCODE)" }

# A kernel pushed before the dataset is ready mounts an empty /kaggle/input and
# dies in seconds. Poll the status endpoint instead of guessing.
Wait-DatasetReady $videoDataset 20
# push_code.ps1 may have just versioned the source dataset too.
Wait-DatasetReady $CodeDataset 10

# ---- 2. generate + push the CPU pipeline kernel ---------------------------
$kernelStage = Join-Path $NammaRoot "kaggle\staging\kernel_$($slug -replace '-', '_')"
Remove-Item -Recurse -Force $kernelStage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $kernelStage | Out-Null
Copy-Item (Join-Path $NammaRoot 'kaggle\kernels\namma_pipeline\namma_pipeline.py') $kernelStage -Force

$kernelMeta = @"
{
  "id": "$kernelRef",
  "title": "namma pipeline $slug",
  "code_file": "namma_pipeline.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": true,
  "enable_gpu": false,
  "enable_internet": true,
  "dataset_sources": [
    "$CodeDataset",
    "$videoDataset"
  ],
  "competition_sources": [],
  "kernel_sources": []
}
"@
[System.IO.File]::WriteAllText((Join-Path $kernelStage 'kernel-metadata.json'), $kernelMeta,
    (New-Object System.Text.UTF8Encoding($false)))

kaggle kernels push -p $kernelStage
if ($LASTEXITCODE -ne 0) { throw "pipeline kernel push failed ($LASTEXITCODE)" }
Write-Host "pipeline pushed: $kernelRef"

if (-not ($Watch -or $Splat)) {
    Write-Host ""
    Write-Host "next: powershell -File kaggle\tools\fetch_output.ps1 $kernelName -Watch -TimeoutMinutes 180"
    Write-Host "then: powershell -File kaggle\tools\push_capture.ps1 -Name $kernelName -DatasetName namma-capture-$slug"
    return
}

# ---- 3. fetch pipeline output ---------------------------------------------
& (Join-Path $PSScriptRoot 'fetch_output.ps1') -Name $kernelName -Watch -TimeoutMinutes $TimeoutMinutes
if ($LASTEXITCODE -ne 0) { throw "pipeline output fetch failed" }

# fetch_output.ps1 downloads logs even for a failed kernel (that is deliberate),
# so success has to be read from the summary rather than inferred from fetch.
$summaryPath = Join-Path $NammaRoot "kaggle\out\$kernelName\out\summary.txt"
if (-not (Test-Path $summaryPath)) { throw "pipeline summary missing: $summaryPath" }
$summaryText = Get-Content $summaryPath -Raw
if ($summaryText -notmatch 'status\s+ok') {
    throw "pipeline kernel failed; inspect $summaryPath`n$summaryText"
}
Write-Host "pipeline status: ok"

if (-not $Splat) {
    Write-Host ""
    Write-Host "pipeline complete. Continue with:"
    Write-Host "  powershell -File kaggle\tools\push_capture.ps1 -Name $kernelName -DatasetName namma-capture-$slug"
    Write-Host "  (then push a splat kernel mounting $captureDataset)"
    return
}

# ---- 4. capture dataset + GPU splat kernel ---------------------------------
& (Join-Path $PSScriptRoot 'push_capture.ps1') -Name $kernelName `
    -DatasetName "namma-capture-$slug" -Title "Namma capture $slug"
if ($LASTEXITCODE -ne 0) { throw "capture dataset upload failed" }

Wait-DatasetReady $captureDataset 20

$splatStage = Join-Path $NammaRoot "kaggle\staging\splat_$($slug -replace '-', '_')"
Remove-Item -Recurse -Force $splatStage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $splatStage | Out-Null
Copy-Item (Join-Path $NammaRoot 'kaggle\kernels\namma_splat\namma_splat.py') $splatStage -Force

$splatMeta = @"
{
  "id": "$splatRef",
  "title": "namma splat $slug",
  "code_file": "namma_splat.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": true,
  "enable_gpu": true,
  "enable_internet": true,
  "dataset_sources": [
    "$CodeDataset",
    "$captureDataset"
  ],
  "competition_sources": [],
  "kernel_sources": []
}
"@
[System.IO.File]::WriteAllText((Join-Path $splatStage 'kernel-metadata.json'), $splatMeta,
    (New-Object System.Text.UTF8Encoding($false)))

kaggle kernels push -p $splatStage
if ($LASTEXITCODE -ne 0) { throw "splat kernel push failed ($LASTEXITCODE)" }

& (Join-Path $PSScriptRoot 'fetch_output.ps1') -Name $splatName -Watch -TimeoutMinutes 300
$splatFile = Join-Path $NammaRoot "kaggle\out\$splatName\out\web\splat.splat"
if (-not (Test-Path $splatFile)) {
    throw "splat kernel produced no web/splat.splat; inspect kaggle\out\$splatName"
}
Write-Host ""
Write-Host "done. artifacts: kaggle\out\$splatName"
Write-Host "stage the web bundle: powershell -File web\tools\sync_artifacts.ps1 -Kernel $splatName -Capture $slug"
