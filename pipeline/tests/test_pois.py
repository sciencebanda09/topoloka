"""POI contract tests: validation, import and web staging.

Run:  .venv\\Scripts\\python.exe -m pytest -s pipeline/tests/test_pois.py
"""

from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from namma import pois, qa  # noqa: E402


def _grid_png(w: int = 10, h: int = 10, blocked: set[tuple[int, int]] | None = None) -> str:
    blocked = blocked or set()
    image = Image.new("L", (w, h), 0)
    for x, y in blocked:
        image.putpixel((x, y), 1)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _nav(w: int = 10, h: int = 10, blocked: set[tuple[int, int]] | None = None) -> dict:
    return {
        "version": 1,
        "cell_m": 0.5,
        "origin": [0.0, 0.0],
        "grid": {"w": w, "h": h, "data_b64": _grid_png(w, h, blocked)},
        "trajectory": [[0.25, 0.25, 1.5], [4.25, 4.25, 1.5]],
    }


def _poi(poi_id: str, x: float, y: float, **over) -> dict:
    return {
        "id": poi_id,
        "name": f"POI {poi_id}",
        "category": "landmark",
        "x": x,
        "y": y,
        **over,
    }


def _write_capture(root: Path, nav: dict, doc: dict | None = None) -> Path:
    capture = root / "demo"
    (capture / "nav").mkdir(parents=True)
    (capture / "nav" / "nav.json").write_text(json.dumps(nav), encoding="utf-8")
    if doc is not None:
        (capture / "nav" / "pois.json").write_text(json.dumps(doc), encoding="utf-8")
    return capture


def test_normalize_valid_pois_and_warn_about_blocked_floor() -> None:
    nav = _nav(blocked={(2, 2)})
    doc = {
        "version": 1,
        "capture": "demo",
        "pois": [
            _poi(
                "free-one", 0.25, 0.25,
                name="  Free   One  ",
                category="  Landmark ",
                aliases=["entry", "entry", " ticket hall "],
                description="  A   useful   place. ",
                source="local",
                view={"x": 0.25, "y": 0.25, "z": 1.5, "yaw": 0.0},
            ),
            _poi("blocked-one", 1.25, 1.25),
        ],
    }
    normalized, warnings = pois.normalize_poi_file(doc, nav=nav, capture="demo")
    assert normalized["version"] == 1
    assert normalized["capture"] == "demo"
    assert [p["id"] for p in normalized["pois"]] == ["free-one", "blocked-one"]
    first = normalized["pois"][0]
    assert first["name"] == "Free One"
    assert first["category"] == "landmark"
    assert first["aliases"] == ["entry", "ticket hall"]
    assert first["description"] == "A useful place."
    assert first["z"] == 0.0
    assert first["radius_m"] == 1.0
    assert "source" not in first
    assert first["view"]["yaw"] == 0.0
    assert "view" not in normalized["pois"][1]
    assert any("blocked/unknown" in w for w in warnings)
    assert any("no view pose" in w for w in warnings)


def test_normalize_rejects_bad_documents() -> None:
    nav = _nav()
    cases = [
        {"version": 2, "pois": [_poi("a", 0.25, 0.25)]},
        {"version": 1, "capture": "other", "pois": [_poi("a", 0.25, 0.25)]},
        {"version": 1, "pois": [_poi("a", 0.25, 0.25), _poi("a", 1.25, 1.25)]},
        {"version": 1, "pois": [_poi("bad id", 0.25, 0.25)]},
        {"version": 1, "pois": [_poi("a", 99.0, 0.25)]},
        {"version": 1, "pois": [_poi("a", float("nan"), 0.25)]},
        {"version": 1, "pois": []},
        {"version": 1, "pois": "nope"},
    ]
    for doc in cases:
        try:
            pois.normalize_poi_file(doc, nav=nav, capture="demo")
        except pois.PoiValidationError:
            continue
        raise AssertionError(f"expected rejection for {doc!r}")


def test_run_pois_writes_normalized_bundle_and_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        capture = _write_capture(root, _nav(blocked={(2, 2)}))
        source = root / "export.json"
        source.write_text(json.dumps({
            "version": 1,
            "capture": "demo",
            "pois": [
                _poi("a", 0.25, 0.25, aliases=["one", "one"],
                     view={"x": 0.25, "y": 0.25, "z": 1.5, "yaw": 0.1}),
                _poi("b", 1.25, 1.25, name="  Blocked  "),
            ],
        }), encoding="utf-8")
        report = pois.run_pois(capture, source=source)
        assert report["count"] == 2
        assert report["categories"] == {"landmark": 2}
        assert any("blocked" in warning for warning in report["warnings"])
        stored = json.loads((capture / "nav" / "pois.json").read_text(encoding="utf-8"))
        assert stored["capture"] == "demo"
        assert stored["pois"][0]["aliases"] == ["one"]
        assert stored["pois"][1]["name"] == "Blocked"
        report_file = json.loads(
            (capture / "nav" / "poi_report.json").read_text(encoding="utf-8"))
        assert report_file["count"] == 2


def test_stage_pois_copies_next_to_nav_and_refuses_invalid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        doc = {"version": 1, "capture": "demo",
               "pois": [_poi("a", 0.25, 0.25, view={
                   "x": 0.25, "y": 0.25, "z": 1.5, "yaw": 0.0})]}
        capture = _write_capture(root, _nav(), doc)
        staged = pois.stage_pois(capture, capture / "web")
        assert staged["present"] is True
        assert staged["count"] == 1
        web_doc = json.loads((capture / "web" / "pois.json").read_text(encoding="utf-8"))
        assert web_doc["pois"][0]["id"] == "a"

        bad = {"version": 1, "capture": "demo",
               "pois": [_poi("a", 0.25, 0.25), _poi("a", 0.75, 0.75)]}
        (capture / "nav" / "pois.json").write_text(json.dumps(bad), encoding="utf-8")
        try:
            pois.stage_pois(capture, capture / "web")
        except SystemExit as exc:
            assert "duplicate" in str(exc)
        else:
            raise AssertionError("invalid POIs must not be packaged")


def test_missing_pois_are_optional_for_packaging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        capture = _write_capture(Path(tmp), _nav())
        staged = pois.stage_pois(capture, capture / "web")
        assert staged == {"present": False, "count": 0, "categories": {}, "warnings": []}


def test_qa_reports_poi_dataset() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        doc = {"version": 1, "capture": "demo",
               "pois": [_poi("a", 0.25, 0.25, view={
                   "x": 0.25, "y": 0.25, "z": 1.5, "yaw": 0.0})]}
        capture = _write_capture(Path(tmp), _nav(), doc)
        checks = qa.run_qa(capture)
        poi_check = next(check for check in checks if check.name == "poi_dataset")
        assert poi_check.status == qa.PASS
        assert "1 POIs" in poi_check.detail

        bad = {"version": 1, "capture": "demo", "pois": []}
        (capture / "nav" / "pois.json").write_text(json.dumps(bad), encoding="utf-8")
        checks = qa.run_qa(capture)
        poi_check = next(check for check in checks if check.name == "poi_dataset")
        assert poi_check.status == qa.FAIL
