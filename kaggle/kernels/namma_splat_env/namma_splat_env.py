"""Kaggle kernel: probe whether nerfstudio (splatfacto) installs cleanly.

CPU kernel -- free, and does not touch GPU quota. Answers, in one run:
  1. what torch/cuda Kaggle ships,
  2. what `pip install nerfstudio` does to those (the known risk: torch downgrade),
  3. whether `ns-train` exists afterwards and still sees CUDA-torch.

Output: /kaggle/working/out/env_report.txt (fetched with kaggle CLI)
"""

import json
import subprocess
import sys
import time
from pathlib import Path

OUT = Path("/kaggle/working/out")
OUT.mkdir(parents=True, exist_ok=True)
LOG = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def probe(label: str) -> None:
    code = (
        "import torch, json;"
        "print(json.dumps({'torch': torch.__version__,"
        "'cuda_build': torch.version.cuda, 'cuda_ok': torch.cuda.is_available()}))"
    )
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        log(f"[{label}] {r.stdout.strip() or r.stderr.strip()[:300]}")
    except Exception as e:
        log(f"[{label}] probe failed: {e}")


def main() -> None:
    t0 = time.time()
    log(f"python {sys.version.split()[0]}")
    probe("before-nerfstudio")

    log("pip install nerfstudio ...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "nerfstudio"],
                       capture_output=True, text=True, timeout=3600)
    log(f"pip exit: {r.returncode}")
    if r.returncode != 0:
        log("pip stderr tail:")
        log((r.stderr or "")[-2000:])

    probe("after-nerfstudio")

    for cmd in (["ns-train", "--help"], ["ns-export", "--help"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            head = (r.stdout or r.stderr).splitlines()[:3]
            log(f"{' '.join(cmd)} exit={r.returncode} head={head}")
        except FileNotFoundError:
            log(f"{' '.join(cmd)}: NOT FOUND on PATH")

    r = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True, timeout=300)
    for line in r.stdout.splitlines():
        low = line.lower()
        if any(k in low for k in ("torch", "gsplat", "nerfstudio", "tyro", "viser", "jaxtyping")):
            log(f"pkg: {line}")

    log(f"elapsed {time.time() - t0:.0f}s")
    (OUT / "env_report.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
