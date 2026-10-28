# kaggle — all compute runs here (CLI-driven)

Machine rule for this project: **local = edit code, git, kaggle CLI only.**
Every pipeline execution (CPU or GPU) runs as a Kaggle kernel.

```
kaggle/
  config.ps1                     KAGGLE_CONFIG_DIR + shared settings
  datasets/namma-code/           dataset: our pipeline source (code.tar -> auto-extracted)
  kernels/namma_pipeline/        kernel: frames -> sfm -> geometry -> qa -> package (CPU)
  kernels/namma_splat/           kernel: depth + 3DGS + package                (GPU)
  tools/push_code.ps1            stage pipeline/ -> code.tar -> dataset version
  tools/push_video.ps1           raw phone video -> dataset -> CPU pipeline kernel
  tools/push_capture.ps1         stage fetched pipeline outputs -> namma-capture-*
  tools/push_kernel.ps1          push a kernel by name
  tools/fetch_output.ps1         download a kernel's outputs to kaggle/out/<kernel>
  out/                           fetched kernel outputs (gitignored)
```

Usage (from repo root):

```powershell
# CPU: video -> frames, SfM, geometry, QA, web bundle
powershell -File kaggle\tools\push_code.ps1
powershell -File kaggle\tools\push_kernel.ps1 namma_pipeline
powershell -File kaggle\tools\fetch_output.ps1 namma_pipeline -Watch -TimeoutMinutes 150

# GPU: depth fusion + dense nav + splat training (needs the capture dataset)
powershell -File kaggle\tools\push_capture.ps1        # then wait for dataset ready
powershell -File kaggle\tools\push_kernel.ps1 namma_splat
powershell -File kaggle\tools\fetch_output.ps1 namma_splat -Watch -TimeoutMinutes 240

# One command for a new live phone capture (CPU + GPU + fetch):
powershell -File kaggle\tools\push_video.ps1 `
  -Video "C:\capture\room.mov" -Name room-v1 -Splat
```

`push_video.ps1` accepts `.mp4`, `.mov`, `.m4v`, `.webm`, `.mkv`, `.avi` — the
phone container is not the constraint. It also refuses to chain the GPU stage
when the CPU summary is not `ok`, so a failed capture does not waste GPU quota.
The full capture → twin runbook is `capture/phone-to-twin.md`.

Kernel status:

```powershell
. .\kaggle\config.ps1
kaggle kernels status shashankdev09/namma-pipeline
```

Quota rules:
- CPU kernels (SfM, geometry, checks) -- do not consume GPU quota. Preferred.
- GPU kernels (depth, 3DGS training) -- share a weekly quota; keep runs deliberate.
- **All scratch work lives in `/tmp/namma`**, never in `/kaggle/working`: the
  kaggle CLI publishes and downloads *everything* under `/kaggle/working`, so
  `code/`, `runs/` and `ns/` checkpoints once turned a 60 MB fetch into a
  ~1 GB partial download that died midway. Only `out/` is written to
  `/kaggle/working` now.

Never commit `kaggle.json`; credentials live in KAGGLE_CONFIG_DIR (dmx checkout).

## Kaggle platform quirks we hit (save yourself the debugging)

- **Dataset uploads auto-extract archives.** A dataset version containing
  `code.tar` or `frames.zip` is stored/mounted as the extracted tree
  (`namma/cli.py`, `frames/*.jpg`). Our kernels therefore accept both forms
  (`stage_code` / `stage_archive` helpers).
- **Never mix tar and zip in the same dataset version.** A version with both
  a `.tar` and a `.zip` hangs in processing forever (status 403 on every API
  call; the dataset never appears in `kaggle datasets list -m`). Tar-only,
  zip-only, and plain-file uploads are all fine. The capture dataset ships
  zips + plain files, deliberately no tar.
- **`kaggle datasets create` skips folders** unless `--dir-mode` is passed;
  we flatten at staging time instead.
- **Windows PowerShell 5.1 `Set-Content -Encoding UTF8` writes a BOM**, which
  breaks the CLI's JSON parser. Use
  `[System.IO.File]::WriteAllText($p, $s, (New-Object System.Text.UTF8Encoding($false)))`.
- **`kaggle kernels status` output** is `<ref> has status "KernelWorkerStatus.X"`
  -- match on `COMPLETE` / `ERROR` (the quotes-in-regex trap in `fetch_output.ps1`).
- **Wait for a dataset version to be `ready` before pushing a kernel that
  mounts it**, otherwise the kernel starts with the dataset missing and fails
  in seconds (`code.tar not found under /kaggle/input`).
- **The kaggle CLI on Windows dies printing unicode** (the kernel log contains
  em-dashes): Python's stdout is cp1252 and raises `charmap codec` mid-download,
  leaving a 0-byte log and exit code 1 even though files downloaded.
  `fetch_output.ps1` sets `PYTHONIOENCODING=utf-8` and retries 3x.
- **pycolmap 4.2.1 API shapes** (cost us one full 28-min kernel run):
  `num_reg_images` / `num_points3D` / `reg_image_ids` and
  `Image.cam_from_world` are **methods** (3.x had properties);
  `Reconstruction.write()` / `write_text()` **require the target directory to
  already exist**; `cam.model` prints as `CameraModelId.SIMPLE_RADIAL`.
  `pipeline/tests/test_sfm_api.py` pins this; run the export paths against a
  fetched `sparse/` model before trusting a full rerun.
- **Extract with `CameraMode.SINGLE`** for a monocular video: pycolmap 4.x
  defaults to one camera *per image*, which produced a ±13% focal spread on
  our real capture; the dmx-slam reference does the same.
- **Windows SIFT crashes with too many threads** (pycolmap native abort inside
  faiss, "more threads crashed pycolmap SIFT on Windows" -- dmx reference).
  `NM_THREADS=4` caps extraction/matching; Linux/Kaggle runs auto.
