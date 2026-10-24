"""Kaggle kernel (GPU): depth fusion + dense nav + splat training for a capture.

Input:  namma-capture-v1 dataset = { frames.zip, transforms.json, sparse.ply,
         poses.json, sparse_txt.zip } (fetched from the namma-pipeline kernel)

Flow (deliberate order -- cheap artifacts first, so a trainer failure never
wastes the run):
    1. metric depth fusion        -> depth/map.npz (dense, meters) + scale.json
    2. geometry on the dense map  -> nav/nav.json (metric costmap) + outline
    3. capture QA                 -> capture_qa.json/md
    4. splatfacto training        -> splat.ply (raw 3DGS)
    5. web conversion             -> splat.splat (32 bytes/gaussian)

Output: /kaggle/working/out/ (fetched with kaggle/tools/fetch_output.ps1)
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
WORK = Path("/kaggle/working")          # only out/ is published as kernel output
SCRATCH = Path("/tmp/namma")            # code/run/ns/export stay OFF the output list
OUT = WORK / "out"
CODE = SCRATCH / "code"
RUN = SCRATCH / "runs" / "corridor_v1"
NS_OUT = SCRATCH / "ns"
ITERS = os.environ.get("NM_ITERS", "25000")
RES = os.environ.get("NM_RES", "1.0")   # train at the frames' native 1600x900
MAX_GAUSSIANS = os.environ.get("NM_MAX_GAUSSIANS", "1500000")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_code() -> None:
    """Extract our pipeline source (code.tar preferred; loose package fallback)."""
    tar = next(INPUT.glob("**/code.tar"), None)
    if tar:
        CODE.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar) as t:
            t.extractall(CODE)
    else:
        cli = next(INPUT.glob("**/namma/cli.py"), None)
        if not cli:
            raise SystemExit("no code.tar and no namma/cli.py under /kaggle/input "
                             "(dataset namma-code missing?)")
        shutil.copytree(cli.parents[1], CODE, dirs_exist_ok=True)
    log(f"code: {sorted(p.name for p in CODE.iterdir())}")


def stage_capture() -> None:
    """Build the capture dir layout the pipeline's stages expect.

    Accepts either shipping form: Kaggle datasets sometimes expose uploaded
    archives pre-extracted (we saw frames.zip arrive as frames/*.jpg), so
    frames/sparse_txt may arrive as zip files or as plain directories, and the
    dataset root may sit at a different mount name. Find it by content, not by
    name, and keep both branch handlers.
    """
    def looks_like_capture(p: Path) -> bool:
        return ((p / "transforms.json").exists() or (p / "frames.zip").exists()
                or (p / "frames").is_dir() or (p / "poses.json").exists())

    def find_root() -> Path | None:
        # 1) the expected mount name (verify it really holds capture files)
        for p in sorted(INPUT.glob("namma-capture-v1*")):
            if p.is_dir() and looks_like_capture(p):
                return p
        # 2) fallback: any mounted dir that looks like our capture
        for marker in ("**/transforms.json", "**/frames.zip", "**/poses.json"):
            for p in sorted(INPUT.glob(marker)):
                cand = p.parent
                if looks_like_capture(cand):
                    return cand
        return None

    root = find_root()
    if root is None:
        tree = [str(p.relative_to(INPUT)) for p in sorted(INPUT.rglob("*"))[:80]]
        raise SystemExit("capture dataset namma-capture-v1 not found; "
                         "/kaggle/input tree (first 80):\n" + "\n".join(tree))
    log(f"capture root: {root}")

    RUN.mkdir(parents=True, exist_ok=True)

    def stage_archive(stem: str, dst: Path) -> None:
        z = root / f"{stem}.zip"
        d = root / stem
        if z.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dst)
        elif d.is_dir():
            shutil.copytree(d, dst, dirs_exist_ok=True)
        else:
            raise SystemExit(f"capture dataset has neither {stem}.zip nor {stem}/")

    stage_archive("frames", RUN / "frames")
    for f in ("transforms.json", "sparse.ply"):
        shutil.copy2(root / f, RUN / f)

    sfm = RUN / "sfm"
    sfm.mkdir(exist_ok=True)
    shutil.copy2(root / "poses.json", sfm / "poses.json")
    stage_archive("sparse_txt", sfm / "sparse_txt")
    shutil.copy2(root / "sparse.ply", sfm / "sparse.ply")
    log(f"capture staged: {len(list((RUN / 'frames').glob('*.jpg')))} frames")


def run_stage(args: list[str]) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    log(f"run: {' '.join(args)}")
    subprocess.run([sys.executable, "-m", "namma.cli", *args],
                   cwd=CODE, env=env, check=True)


def ensure_nerfstudio() -> str:
    import importlib.metadata

    try:
        import nerfstudio  # noqa: F401
    except ImportError:
        log("nerfstudio missing; pip install (this takes a few minutes)")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "nerfstudio==1.1.5"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"pip install nerfstudio failed:\n{(r.stderr or '')[-2000:]}")
        import importlib
        importlib.invalidate_caches()
    # nerfstudio's __init__.py is license-only (no __version__) -- read the
    # distribution metadata instead
    return importlib.metadata.version("nerfstudio")


def ensure_transformers() -> None:
    try:
        import transformers  # noqa: F401
    except ImportError:
        log("transformers missing; pip install")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transformers"],
                       check=True)


def check_cuda() -> None:
    code = ("import torch;"
            "print(torch.cuda.is_available(), torch.cuda.device_count(), "
            "torch.__version__, torch.version.cuda, "
            "torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    log(f"cuda probe: {r.stdout.strip()} {r.stderr.strip()[:200]}")
    if "True" not in r.stdout:
        raise SystemExit("CUDA unavailable after install; refusing to train on CPU")


TRAIN_SNIPPET = r'''
"""Train splatfacto via nerfstudio's Python API (no tyro CLI).

`ns-train`'s dataparser is a tyro subcommand, and its flag grammar differs
between tyro versions (older: `--auto-scale-poses False`; 1.x: `--no-auto-scale-poses`)
and requires the `nerfstudio-data` token in a specific position. Building the
TrainerConfig directly is version-proof and logs every setting.
"""
import copy
import sys
from pathlib import Path

from nerfstudio.configs.method_configs import method_configs
from nerfstudio.data.dataparsers.nerfstudio_dataparser import NerfstudioDataParserConfig

RUN = Path(sys.argv[1])
NS_OUT = Path(sys.argv[2])
ITERS = int(sys.argv[3])
RES = float(sys.argv[4])

cfg = copy.deepcopy(method_configs["splatfacto"])
cfg.output_dir = NS_OUT
cfg.experiment_name = "capture"
cfg.timestamp = "run1"
cfg.max_num_iterations = ITERS
cfg.viewer.quit_on_train_completion = True
cfg.pipeline.model.cull_alpha_thresh = 0.005
cfg.pipeline.datamanager.camera_res_scale_factor = RES
# Keep OUR frame: no auto-orient/center/scale, seed from the SfM cloud.
cfg.pipeline.datamanager.dataparser = NerfstudioDataParserConfig(
    data=RUN,
    orientation_method="none",
    center_method="none",
    auto_scale_poses=False,
    load_3D_points=True,
)
print("base dir:", cfg.get_base_dir(), flush=True)
print("dataparser:", cfg.pipeline.datamanager.dataparser, flush=True)
cfg.save_config()
trainer = cfg.setup(local_rank=0, world_size=1)
trainer.setup()
trainer.train()
print("TRAIN_DONE", flush=True)
'''


def train() -> Path:
    script = SCRATCH / "train_api.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(TRAIN_SNIPPET, encoding="utf-8")
    cmd = [sys.executable, str(script), str(RUN), str(NS_OUT), ITERS, RES]
    log(" ".join(cmd))
    # gsplat is installed from source here (no cp313/cu128 wheel), so the first
    # import JIT-builds ~26 .cu files. The default MAX_JOBS (=cpu count) launched
    # four heavy nvcc processes and the node killed the build mid-file. Two at
    # a time is ~2x slower but stays inside the host RAM.
    env = os.environ.copy()
    env["MAX_JOBS"] = os.environ.get("NM_MAX_JOBS", "1")
    env["TORCH_CUDA_ARCH_LIST"] = "7.5"          # T4
    env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=6 * 3600,
                       env=env)
    log(f"train exit {r.returncode}")
    log((r.stdout or "")[-600:])
    if r.returncode != 0 or "TRAIN_DONE" not in (r.stdout or ""):
        tail = (r.stderr or "")[-3000:] + (r.stdout or "")[-1500:]
        raise SystemExit(f"training failed (exit {r.returncode}):\n{tail}")
    configs = sorted(NS_OUT.glob("capture/splatfacto/*/config.yml"))
    if not configs:
        raise SystemExit("no config.yml found after training")
    log(f"config: {configs[-1]}")
    return configs[-1]


EXPORT_SNIPPET = r'''
"""Export the trained splat, tolerating torch>=2.6's weights_only default.

nerfstudio 1.1.5 calls torch.load() without weights_only=..., while torch>=2.6
defaults it to True; our checkpoint records numpy scalars in the dataparser
metadata, which the strict loader rejects. The checkpoint was produced by our
own training run minutes earlier, so restore the legacy behaviour.
"""
import sys
from pathlib import Path

import torch

_orig_load = torch.load


def _load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)


torch.load = _load

from nerfstudio.scripts.exporter import ExportGaussianSplat  # noqa: E402

config = Path(sys.argv[1])
out = Path(sys.argv[2])
ExportGaussianSplat(load_config=config, output_dir=out).main()
print("EXPORT_DONE", flush=True)
'''


def export_splat(config: Path) -> Path:
    export_dir = SCRATCH / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    script = SCRATCH / "export_api.py"
    script.write_text(EXPORT_SNIPPET, encoding="utf-8")
    cmd = [sys.executable, str(script), str(config), str(export_dir)]
    log(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    log(f"export exit {r.returncode}")
    log((r.stdout or "")[-500:])
    if r.returncode != 0 or "EXPORT_DONE" not in (r.stdout or ""):
        raise SystemExit(f"export failed:\n{(r.stderr or '')[-2000:]}")
    plys = sorted(export_dir.glob("*.ply"))
    if not plys:
        raise SystemExit("no ply exported")
    return plys[0]


def convert(ply: Path) -> None:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "namma.cli", "splat-convert",
           str(ply), str(RUN / "splat" / "splat.splat"),
           "--max-gaussians", MAX_GAUSSIANS]
    r = subprocess.run(cmd, cwd=CODE, env=env, capture_output=True, text=True, timeout=1800)
    log(f"splat-convert exit {r.returncode}")
    if r.returncode != 0:
        raise SystemExit(f"splat-convert failed:\n{(r.stderr or '')[-2000:]}")


def collect() -> None:
    web = RUN / "web"
    if web.is_dir():
        dst = OUT / "web"
        dst.mkdir(exist_ok=True)
        for f in sorted(web.iterdir()):
            if f.is_file():
                shutil.copy2(f, dst / f.name)
    for rel in ("depth/scale.json", "depth/depth_report.json", "depth/map.npz",
                "capture_qa.json", "capture_qa.md", "metricize.json",
                "nav/nav.json", "nav/nav_report.json"):
        src = RUN / rel
        if src.exists():
            shutil.copy2(src, OUT / Path(rel).name)
    log(f"out: {sorted(p.name for p in OUT.iterdir())}")


def main() -> None:
    t0 = time.time()
    error = None
    ns_version = ""
    stage_errors: dict[str, str] = {}
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        stage_code()
        stage_capture()
    except BaseException:  # SystemExit included -- reports must never lie
        error = "capture staging failed"
        stage_errors["staging"] = traceback.format_exc()
        log("STAGING ERROR:\n" + stage_errors["staging"])
    if not error:
        # Depth/geometry/QA are valuable but NOT prerequisites for training
        # (the splat needs only transforms.json + sparse.ply + frames). A
        # failure in any of them is recorded and must not burn the GPU run.
        try:
            ensure_transformers()
            run_stage(["depth", str(RUN)])
        except BaseException:
            stage_errors["depth"] = traceback.format_exc()
            log("DEPTH ERROR (training continues):\n" + stage_errors["depth"])
        try:
            cloud = RUN / "depth" / "map.npz"
            if cloud.exists():
                run_stage(["geometry", str(RUN), "--cloud", str(cloud)])
            else:
                log("no depth map; geometry falls back to the sparse cloud")
                run_stage(["geometry", str(RUN)])
        except BaseException:
            stage_errors["geometry"] = traceback.format_exc()
            log("GEOMETRY ERROR (training continues):\n" + stage_errors["geometry"])
        try:
            run_stage(["qa", str(RUN)])
        except BaseException:
            stage_errors["qa"] = traceback.format_exc()
            log("QA ERROR (training continues):\n" + stage_errors["qa"])
    metricized = False
    if not error:
        # Frame contract: nav.json's align maps the SPLAT'S TRAINING FRAME ->
        # nav. With a depth scale present, align was built against the metric
        # cloud, so the splat must train in metric units too (see
        # namma/metricize.py). Without a depth scale, geometry aligned the SfM
        # cloud and SfM-frame training is already consistent.
        if (RUN / "depth" / "scale.json").exists():
            try:
                run_stage(["metricize", str(RUN)])
                metricized = True
            except BaseException:
                stage_errors["metricize"] = traceback.format_exc()
                log("METRICIZE ERROR (skipping training -- a splat trained in "
                    "SfM units would not match nav.json's metric align):\n"
                    + stage_errors["metricize"])
                error = "metricize failed"
        else:
            log("no depth scale; splat trains in SfM units (align covers that frame)")
    if not error:
        try:
            ns_version = ensure_nerfstudio()
            log(f"nerfstudio {ns_version}")
            check_cuda()
            config = train()
            ply = export_splat(config)
            shutil.copy2(ply, OUT / "splat.ply")
            convert(ply)
        except BaseException:
            error = "splat stage failed"
            stage_errors["splat"] = traceback.format_exc()
            log("SPLAT ERROR:\n" + stage_errors["splat"])
            # Never lose a finished training run to a downstream bug: publish
            # the checkpoint + config so an export fix can reuse them.
            try:
                run_dirs = sorted(NS_OUT.glob("capture/splatfacto/*"))
                if run_dirs:
                    ns_dst = OUT / "ns"
                    ns_dst.mkdir(exist_ok=True)
                    cfg_file = run_dirs[-1] / "config.yml"
                    if cfg_file.exists():
                        shutil.copy2(cfg_file, ns_dst / "config.yml")
                    for ck in (run_dirs[-1] / "nerfstudio_models").glob("*.ckpt"):
                        shutil.copy2(ck, ns_dst / ck.name)
                    log(f"checkpoint preserved: {sorted(p.name for p in ns_dst.iterdir())}")
            except Exception:
                log("checkpoint preservation failed:\n" + traceback.format_exc())
    # packaging runs whenever the minimal inputs exist (nav.json + a cloud) --
    # a trainer failure must never cost us the dense nav bundle. Without a
    # splat the viewer still works in point-cloud mode.
    try:
        run_stage(["package", str(RUN)])
    except BaseException:
        stage_errors["package"] = traceback.format_exc()
        log("PACKAGE ERROR:\n" + stage_errors["package"])
        if not error:
            error = "package stage failed"
    try:
        collect()
    except Exception:
        log("collect failed:\n" + traceback.format_exc())
    report = {
        "kernel": "namma_splat_corridor",
        "nerfstudio": ns_version,
        "iterations": ITERS,
        "metricized": metricized,
        "elapsed_s": round(time.time() - t0, 1),
        "status": error or "ok",
        "errors": stage_errors,
        "out": sorted(p.name for p in OUT.iterdir()),
    }
    (OUT / "train_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
