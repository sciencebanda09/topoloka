"""POI authoring contract: validate, normalize and stage `pois.json`.

The browser can export tags it created locally (`Export pois.json`). Drop that
file at `<capture>/nav/pois.json`, run `namma pois <capture>` (or just
`namma package <capture>`) and the tags become authored data in the web bundle.

Validation is intentionally split by severity:

* malformed documents / bad ids / duplicate ids / non-finite or out-of-grid
  coordinates  -> hard error (packaging must not ship a broken index)
* POIs on blocked or unknown cells, missing camera views, duplicate names
  -> warnings (the viewer can still snap a route and show a label)

The web app builds the actual spatial index at load time; this module owns the
data contract and the packaging boundary, not query behaviour.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
MAX_POIS = 10_000
FREE = 0


class PoiValidationError(ValueError):
    """A POI file that must not be packaged."""


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == float(value) and abs(float(value)) != float("inf")


def _decode_grid(nav: dict[str, Any]) -> tuple[int, int, Any] | None:
    """Return (w, h, pixel accessor) for the nav grid, or None when absent."""
    grid = nav.get("grid") or {}
    data_b64 = grid.get("data_b64")
    if not data_b64:
        return None
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(data_b64))).convert("L")
    except Exception:
        return None
    return image.width, image.height, image.load()


def _grid_value(
    nav: dict[str, Any],
    decoded: tuple[int, int, Any],
    x: float,
    y: float,
) -> int | None:
    grid = nav.get("grid") or {}
    w = int(grid.get("w") or 0)
    h = int(grid.get("h") or 0)
    cell = float(nav.get("cell_m") or 0.05)
    origin = nav.get("origin") or [0.0, 0.0]
    if w <= 0 or h <= 0 or cell <= 0:
        return None
    cx = int((x - float(origin[0])) // cell)
    cy = int((y - float(origin[1])) // cell)
    if not (0 <= cx < w and 0 <= cy < h):
        return None
    iw, ih, pixel = decoded
    if (iw, ih) != (w, h):
        # The encoded PNG is authoritative; nav.json dimensions should match.
        cx = int(cx * iw / w)
        cy = int(cy * ih / h)
    return int(pixel[cx, cy])  # grayscale palette: 0 free, 1 obstacle, 2 unknown


def _normalize_view(raw: Any, index: int, errors: list[str]) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append(f"pois[{index}].view must be an object")
        return None
    keys = ("x", "y", "z", "yaw")
    missing = [key for key in keys if not _finite(raw.get(key))]
    if missing:
        errors.append(f"pois[{index}].view has non-finite/missing {', '.join(missing)}")
        return None
    pitch = raw.get("pitch", 0.0)
    if not _finite(pitch):
        errors.append(f"pois[{index}].view.pitch must be finite")
        return None
    return {
        "x": float(raw["x"]),
        "y": float(raw["y"]),
        "z": float(raw["z"]),
        "yaw": float(raw["yaw"]),
        "pitch": float(pitch),
    }


def normalize_poi_file(
    doc: Any,
    nav: dict[str, Any] | None = None,
    capture: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate and normalize a POI document.

    Raises `PoiValidationError` for errors that would make the index ambiguous
    or unaddressable. Returns `(normalized_document, warnings)` otherwise.
    """
    if not isinstance(doc, dict):
        raise PoiValidationError("pois.json must be a JSON object")
    version = doc.get("version", 1)
    if version != 1:
        raise PoiValidationError(f"unsupported pois.json version {version!r} (expected 1)")
    if capture and doc.get("capture") and str(doc["capture"]) != capture:
        raise PoiValidationError(
            f"pois.json capture is {doc['capture']!r}, expected {capture!r}"
        )
    raw_pois = doc.get("pois")
    if not isinstance(raw_pois, list):
        raise PoiValidationError("pois.json must contain a `pois` array")
    if len(raw_pois) > MAX_POIS:
        raise PoiValidationError(f"pois.json has {len(raw_pois)} POIs (max {MAX_POIS})")

    grid = (nav or {}).get("grid") or {}
    origin = (nav or {}).get("origin") or [0.0, 0.0]
    cell = float((nav or {}).get("cell_m") or 0.05)
    gw, gh = int(grid.get("w") or 0), int(grid.get("h") or 0)
    has_bounds = bool(nav and gw > 0 and gh > 0 and cell > 0)
    decoded = _decode_grid(nav) if nav else None

    errors: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    names: Counter[str] = Counter()
    normalized: list[dict[str, Any]] = []
    blocked: list[str] = []
    missing_view: list[str] = []

    for index, raw in enumerate(raw_pois):
        if not isinstance(raw, dict):
            errors.append(f"pois[{index}] must be an object")
            continue

        poi_id = raw.get("id")
        if not isinstance(poi_id, str) or not ID_RE.match(poi_id.strip()):
            errors.append(
                f"pois[{index}].id must match [a-zA-Z0-9][a-zA-Z0-9_-]{{0,63}}"
            )
            continue
        poi_id = poi_id.strip()
        if poi_id in seen_ids:
            errors.append(f"duplicate POI id {poi_id!r}")
            continue
        seen_ids.add(poi_id)

        name = raw.get("name")
        if not isinstance(name, str) or not _collapse(name):
            errors.append(f"pois[{index}].name must be a non-empty string")
            continue
        name = _collapse(name)
        if len(name) > 80:
            errors.append(f"pois[{index}].name is longer than 80 characters")
            continue

        category = raw.get("category", "place")
        if not isinstance(category, str) or not _collapse(category):
            errors.append(f"pois[{index}].category must be a non-empty string")
            continue
        category = _collapse(category).lower()

        x, y = raw.get("x"), raw.get("y")
        if not (_finite(x) and _finite(y)):
            errors.append(f"pois[{index}].x/y must be finite numbers")
            continue
        x, y = float(x), float(y)
        if has_bounds:
            xmin, ymin = float(origin[0]), float(origin[1])
            xmax, ymax = xmin + gw * cell, ymin + gh * cell
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                errors.append(
                    f"pois[{index}] ({poi_id}) is outside the nav grid "
                    f"[{xmin:.2f}..{xmax:.2f}, {ymin:.2f}..{ymax:.2f}]"
                )
                continue

        z = raw.get("z", 0.0)
        if not _finite(z):
            errors.append(f"pois[{index}].z must be finite")
            continue
        radius = raw.get("radius_m", 1.0)
        if not _finite(radius) or not (0.1 <= float(radius) <= 20):
            errors.append(f"pois[{index}].radius_m must be between 0.1 and 20")
            continue

        aliases_raw = raw.get("aliases", [])
        if not isinstance(aliases_raw, list):
            errors.append(f"pois[{index}].aliases must be an array")
            continue
        aliases: list[str] = []
        for alias in aliases_raw:
            if not isinstance(alias, str):
                errors.append(f"pois[{index}].aliases must contain strings")
                break
            alias = _collapse(alias)
            if alias and alias not in aliases:
                aliases.append(alias)
        else:
            if len(aliases) > 20:
                errors.append(f"pois[{index}] has more than 20 aliases")
                continue

            description = raw.get("description", "")
            if not isinstance(description, str):
                errors.append(f"pois[{index}].description must be a string")
                continue
            description = _collapse(description)
            if len(description) > 240:
                description = description[:239].rstrip() + "…"

            view = _normalize_view(raw.get("view"), index, errors)
            poi: dict[str, Any] = {
                "id": poi_id,
                "name": name,
                "category": category,
                "x": x,
                "y": y,
                "z": float(z),
                "radius_m": float(radius),
            }
            if aliases:
                poi["aliases"] = aliases
            if description:
                poi["description"] = description
            if view is not None:
                poi["view"] = view
            else:
                missing_view.append(poi_id)

            value = _grid_value(nav, decoded, x, y) if nav and decoded else None
            if value is not None and value != FREE:
                blocked.append(poi_id)
            normalized.append(poi)
            names[name.casefold()] += 1

    if errors:
        raise PoiValidationError("; ".join(errors))
    if not normalized:
        raise PoiValidationError("pois.json contains no usable POIs")

    duplicate_names = [name for name, count in names.items() if count > 1]
    if duplicate_names:
        warnings.append(f"duplicate POI names: {', '.join(sorted(duplicate_names))}")
    if blocked:
        shown = ", ".join(blocked[:6]) + ("…" if len(blocked) > 6 else "")
        warnings.append(f"{len(blocked)} POI(s) sit on blocked/unknown cells ({shown}); routes snap to nearby floor")
    if missing_view:
        shown = ", ".join(missing_view[:6]) + ("…" if len(missing_view) > 6 else "")
        warnings.append(f"{len(missing_view)} POI(s) have no view pose ({shown}); jump uses the POI position")

    return {
        "version": 1,
        "capture": capture or doc.get("capture"),
        "pois": normalized,
    }, warnings


def read_poi_file(
    path: Path,
    nav: dict[str, Any] | None = None,
    capture: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PoiValidationError(f"missing POI file: {path}") from exc
    except ValueError as exc:
        raise PoiValidationError(f"{path} is not valid JSON: {exc}") from exc
    return normalize_poi_file(doc, nav=nav, capture=capture)


def _load_nav(capture_dir: Path) -> dict[str, Any] | None:
    path = capture_dir / "nav" / "nav.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PoiValidationError(f"{path} is not valid JSON: {exc}") from exc


def run_pois(capture_dir: Path, source: Path | None = None) -> dict[str, Any]:
    """Validate/import POIs and write the canonical `nav/pois.json` + report."""
    capture_dir = Path(capture_dir)
    src = Path(source) if source else capture_dir / "nav" / "pois.json"
    if not src.exists():
        raise SystemExit(f"missing {src} (export POIs from the viewer, then pass --source)")
    nav = _load_nav(capture_dir)
    try:
        doc, warnings = read_poi_file(src, nav=nav, capture=capture_dir.name)
    except PoiValidationError as exc:
        raise SystemExit(f"[pois] invalid: {exc}") from exc

    dest = capture_dir / "nav" / "pois.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    categories = Counter(poi["category"] for poi in doc["pois"])
    report = {
        "stage": "pois",
        "capture": capture_dir.name,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(src),
        "count": len(doc["pois"]),
        "categories": dict(sorted(categories.items())),
        "warnings": warnings,
    }
    report_path = capture_dir / "nav" / "poi_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[pois] {report['count']} POIs ({len(categories)} categories) -> {dest}")
    for warning in warnings:
        print(f"  WARN {warning}")
    return report


def stage_pois(capture_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Validate `nav/pois.json` and copy it beside `nav.json` in the web bundle."""
    capture_dir = Path(capture_dir)
    src = capture_dir / "nav" / "pois.json"
    if not src.exists():
        return {"present": False, "count": 0, "categories": {}, "warnings": []}
    nav = _load_nav(capture_dir)
    try:
        doc, warnings = read_poi_file(src, nav=nav, capture=capture_dir.name)
    except PoiValidationError as exc:
        raise SystemExit(f"[package] invalid nav/pois.json: {exc}") from exc
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pois.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    categories = Counter(poi["category"] for poi in doc["pois"])
    for warning in warnings:
        print(f"  WARN {warning}")
    return {
        "present": True,
        "count": len(doc["pois"]),
        "categories": dict(sorted(categories.items())),
        "warnings": warnings,
    }
