"""Kaggle kernel (GPU): train the Gaussian splat for a capture and export web artifacts.

Input:  namma-capture-v1 dataset = { frames.zip, transforms.json, sparse.ply }
Output: /kaggle/working/out/ = { splat.ply (raw 3DGS), splat.splat (web format),
                                 splat_convert_report.json, train_report.json }

Trainer: nerfstudio splatfacto (the same proven path used by the Syntheta repo;
their gsplat trainer is a stub). The kernel probes the environment first and
aborts loudly if the pip install broke CUDA, rather than training on CPU.
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile
from pathlib import Path

INPUT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
OUT = WORK / "out"
CODE = WORK / "code"
RUN = WORK / "run"
NS_OUT = WORK / "ns"
ITERS = os.environ.get("NM_ITERS", "15000")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_code() -> None:
    tar = next(INPUT.glob("**/code.tar"), None)
    if not tar:
        raise SystemExit("code.tar missing (dataset namma-code)")
    CODE.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar) as t:
        t.extractall(CODE)
    log(f"code: {sorted(p.name for p in CODE.iterdir())}")


def stage_capture() -> None:
    root = next(INPUT.glob("namma-capture-v1*"), None)
    if not root or not root.is_dir():
        raise SystemExit("capture dataset namma-capture-v1 missing")
    RUN.mkdir(parents=True, exist_ok=True)
    zips = list(root.glob("frames.zip"))
    if not zips:
        raise SystemExit("frames.zip missing in capture dataset")
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(RUN / "frames")
    shutil.copy2(root / "transforms.json", RUN / "transforms.json")
    if (root / "sparse.ply").exists():
        shutil.copy2(root / "sparse.ply", RUN / "sparse.ply")
    log(f"capture staged: {len(list((RUN / 'frames').glob('*.jpg')))} frames")


def ensure_nerfstudio() -> str:
    try:
        import nerfstudio
        return nerfstudio.__version__
    except ImportError:
        log("nerfstudio missing; pip install (this takes a few minutes)")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "nerfstudio"], check=True)
        import importlib
        importlib.invalidate_caches()
        import nerfstudio
        return nerfstudio.__version__


def check_cuda() -> None:
    code = "import torch;print(torch.cuda.is_available(), torch.__version__, torch.version.cuda)"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    log(f"cuda probe: {r.stdout.strip()} {r.stderr.strip()[:200]}")
    if "True" not in r.stdout:
        raise SystemExit("CUDA unavailable after install; refusing to train on CPU")


def train() -> Path:
    cmd = [
        "ns-train", "splatfacto",
        "--data", str(RUN),
        "--output-dir", str(NS_OUT),
        "--experiment-name", "capture",
        "--timestamp", "run1",
        "--max-num-iterations", ITERS,
        "--viewer.quit-on-train-completion", "True",
        "--pipeline.model.cull-alpha-thresh", "0.005",
    ]
    log(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600)
    log(f"ns-train exit {r.returncode}")
    if r.returncode != 0:
        tail = (r.stderr or "")[-3000:] + (r.stdout or "")[-1000:]
        raise SystemExit(f"ns-train failed:\n{tail}")
    configs = sorted(NS_OUT.glob("capture/splatfacto/*/config.yml"))
    if not configs:
        raise SystemExit("no config.yml found after training")
    log(f"config: {configs[-1]}")
    return configs[-1]


def export(config: Path) -> Path:
    export_dir = WORK / "export"
    cmd = ["ns-export", "gaussian-splat", "--load-config", str(config),
           "--output-dir", str(export_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    log(f"ns-export exit {r.returncode}")
    if r.returncode != 0:
        raise SystemExit(f"ns-export failed:\n{(r.stderr or '')[-2000:]}")
    plys = list(export_dir.glob("*.ply"))
    if not plys:
        raise SystemExit("no ply exported")
    return plys[0]


def convert(ply: Path) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "namma.cli", "splat-convert",
           str(ply), str(OUT / "splat.splat")]
    r = subprocess.run(cmd, cwd=CODE, env=env, capture_output=True, text=True, timeout=1800)
    log(f"splat-convert exit {r.returncode}")
    if r.returncode != 0:
        raise SystemExit(f"splat-convert failed:\n{(r.stderr or '')[-2000:]}")


def main() -> None:
    t0 = time.time()
    error = None
    ns_version = ""
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        stage_code()
        stage_capture()
        ns_version = ensure_nerfstudio()
        log(f"nerfstudio {ns_version}")
        check_cuda()
        config = train()
        ply = export(config)
        shutil.copy2(ply, OUT / "splat.ply")
        convert(ply)
    except Exception:
        error = traceback.format_exc()
        log("ERROR:\n" + error)
    finally:
        report = {
            "kernel": "namma_splat",
            "nerfstudio": ns_version,
            "iterations": ITERS,
            "elapsed_s": round(time.time() - t0, 1),
            "status": "error" if error else "ok",
            "error": error,
            "out": sorted(p.name for p in OUT.iterdir()) if OUT.exists() else [],
        }
        (OUT / "train_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        log("done")


if __name__ == "__main__":
    main()
