# Shared config for all kaggle tooling. Dot-source: `. .\kaggle\config.ps1`
$env:KAGGLE_CONFIG_DIR = "C:\Users\kumar\OneDrive\Desktop\Project\Syntheta\dmx-pipeline\house_video"

$script:NammaRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:NammaUser   = "shashankdev09"
$script:CodeDataset = "$script:NammaUser/namma-code"
$script:VideoDataset = "$script:NammaUser/house-video-v2-input"
