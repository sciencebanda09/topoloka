"""Lazy-import contract test.

The Kaggle GPU kernel runs `python -m namma.cli depth|geometry|qa|package`
without pycolmap/torch/transformers installed. `cli.py` imports every stage
module, so heavy and GPU-only dependencies must be imported INSIDE functions.
This test blocks them at the meta-path level and asserts the CLI still loads.

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_lazy_imports.py
"""

from __future__ import annotations

import importlib.abc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BLOCKED = {"pycolmap", "torch", "transformers"}


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError(f"{fullname} blocked by lazy-import test")
        return None


def main() -> None:
    # drop anything already imported so the block actually bites
    for mod in list(sys.modules):
        if mod.split(".")[0] in BLOCKED:
            del sys.modules[mod]
    sys.meta_path.insert(0, Blocker())

    import namma.cli  # noqa: F401
    import namma.depth  # noqa: F401
    import namma.geometry  # noqa: F401
    import namma.package  # noqa: F401
    import namma.qa  # noqa: F401
    import namma.sfm  # noqa: F401
    import namma.splat_convert  # noqa: F401

    print("OK: namma.cli and all stages import with pycolmap/torch/transformers blocked")


if __name__ == "__main__":
    main()
