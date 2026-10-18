# kaggle — all compute runs here (CLI-driven)

Machine rule for this project: **local = edit code, git, kaggle CLI only.**
Every pipeline execution (CPU or GPU) runs as a Kaggle kernel.

```
kaggle/
  config.ps1                     KAGGLE_CONFIG_DIR + shared settings
  datasets/namma-code/           dataset: our pipeline source, shipped as code.tar
  kernels/namma_pipeline/        kernel: frames -> sfm  (CPU)
  kernels/namma_splat/           kernel: depth + 3DGS    (GPU)   [later]
  tools/push_code.ps1            stage pipeline/ -> code.tar -> kaggle datasets create/version
  tools/push_kernel.ps1          push a kernel by name
  tools/fetch_output.ps1         download a kernel's outputs to kaggle/out/<kernel>
  out/                           fetched kernel outputs (gitignored)
```

Usage (from repo root):

```powershell
powershell -File kaggle\tools\push_code.ps1                  # sync pipeline code to Kaggle
powershell -File kaggle\tools\push_kernel.ps1 namma_pipeline  # run the pipeline kernel
powershell -File kaggle\tools\fetch_output.ps1 namma_pipeline
```

Kernel status:

```powershell
. .\kaggle\config.ps1
kaggle kernels status shashankdev09/namma-pipeline
```

Quota rules:
- CPU kernels (SfM, geometry, checks) -- do not consume GPU quota. Preferred.
- GPU kernels (depth, 3DGS training) -- share a weekly quota; keep runs deliberate,
  write checkpoints to /kaggle/working so partial runs are never wasted.

Never commit `kaggle.json`; credentials live in KAGGLE_CONFIG_DIR (dmx checkout).
