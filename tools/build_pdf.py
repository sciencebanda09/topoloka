"""Render a Markdown document to PDF via pandoc + headless Chrome/Edge.

Usage:
    python tools/build_pdf.py docs/abstract.md docs/abstract.pdf
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> Path:
    for cand in CHROME_CANDIDATES:
        if cand.exists():
            return cand
    for name in ("google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit("No Chrome/Edge binary found for PDF printing.")


def build_pdf(doc: Path, out: Path, css: Path) -> int:
    if not doc.exists():
        raise SystemExit(f"Input markdown not found: {doc}")
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise SystemExit("pandoc not found on PATH.")
    browser = find_browser()

    out.parent.mkdir(parents=True, exist_ok=True)
    local_temp = Path.home() / "AppData" / "Local" / "Temp"
    base_tmp = str(local_temp) if local_temp.is_dir() else None
    with tempfile.TemporaryDirectory(dir=base_tmp) as tmp:
        html_path = Path(tmp) / "doc.html"
        subprocess.run(
            [
                pandoc,
                str(doc),
                "-f",
                "gfm",
                "-t",
                "html5",
                "-s",
                "-c",
                str(css),
                "--embed-resources",
                f"--resource-path={doc.parent}",
                "-o",
                str(html_path),
            ],
            check=True,
        )
        uri = html_path.resolve().as_uri()
        profile_dir = Path(tmp) / "profile"
        subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile_dir}",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out.resolve()}",
                uri,
            ],
            check=False,
            timeout=60,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not out.exists():
        raise SystemExit(f"PDF was not produced: {out}")

    raw = out.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page\b", raw))
    print(f"PDF: {out} ({len(raw) / 1024:.0f} KB, {pages} pages)")
    return pages


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc", nargs="?", default="docs/abstract.md", help="Input markdown path")
    ap.add_argument("output", nargs="?", default="docs/abstract.pdf", help="Output PDF path")
    ap.add_argument("--css", default="docs/abstract.css", help="Stylesheet path")
    args = ap.parse_args()

    doc = (ROOT / args.doc) if not Path(args.doc).is_absolute() else Path(args.doc)
    out = (ROOT / args.output) if not Path(args.output).is_absolute() else Path(args.output)
    css = (ROOT / args.css) if not Path(args.css).is_absolute() else Path(args.css)
    build_pdf(doc, out, css)


if __name__ == "__main__":
    sys.exit(main())
