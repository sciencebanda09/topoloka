"""Regression tests for the pycolmap API-shape helpers in namma.sfm.

pycolmap 3.x exposed `Reconstruction.num_reg_images` etc. as properties;
4.2.1 makes them METHODS and moves camera data behind `cam_from_world()`.
The 2026-10-18 Kaggle run crashed on exactly this (`TypeError: '<' not
supported between instances of 'method' and 'method'`), so these helpers are
pinned here with fake objects that mimic both API generations.

Run:  .venv\\Scripts\\python.exe pipeline\\tests\\test_sfm_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from namma import sfm  # noqa: E402


class Rigid4x:
    """Mimics pycolmap 4.x Rigid3d: rotation/translation are properties."""

    class Rotation:
        @property
        def matrix(self) -> np.ndarray:
            return np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])

    @property
    def rotation(self) -> Rotation:
        return self.Rotation()

    @property
    def translation(self) -> np.ndarray:
        return np.array([1.0, 2.0, 3.0])


class Rigid3xCallable:
    """Mimics pycolmap 3.x Rigid3d: rotation/translation are methods."""

    class Rotation:
        def matrix(self) -> np.ndarray:
            return np.eye(3)

    def rotation(self) -> Rotation:
        return self.Rotation()

    def translation(self) -> np.ndarray:
        return np.array([1.0, 2.0, 3.0])


class Rec4x:
    """Mimics pycolmap 4.x Reconstruction: counters are methods."""

    def __init__(self, n: int) -> None:
        self._n = n

    def num_reg_images(self) -> int:
        return self._n

    def num_points3D(self) -> int:
        return self._n * 10

    def reg_image_ids(self) -> list[int]:
        return list(range(self._n))


class Rec3x:
    """Mimics pycolmap 3.x Reconstruction: counters are properties."""

    def __init__(self, n: int) -> None:
        self._n = n

    @property
    def num_reg_images(self) -> int:
        return self._n

    @property
    def num_points3D(self) -> int:
        return self._n * 10

    @property
    def reg_image_ids(self) -> list[int]:
        return list(range(self._n))


class FakeCam4x:
    class Model:
        name = "SIMPLE_RADIAL"

        def __str__(self) -> str:  # what 4.x actually prints
            return "CameraModelId.SIMPLE_RADIAL"

    model = Model()
    width, height = 1600, 900
    params = [1500.0, 800.0, 450.0, 0.01]

    @property
    def focal_length_x(self) -> float:
        return 1500.0

    @property
    def focal_length_y(self) -> float:
        return 1500.0

    @property
    def principal_point_x(self) -> float:
        return 800.0

    @property
    def principal_point_y(self) -> float:
        return 450.0


def test_get_handles_methods_and_properties() -> None:
    assert sfm._get(Rec4x(157), "num_reg_images") == 157
    assert sfm._get(Rec3x(157), "num_reg_images") == 157
    assert sfm._get(Rec4x(3), "reg_image_ids") == [0, 1, 2]


def test_model_sorting_across_api_shapes() -> None:
    # the exact failing call from the Kaggle run
    recs = [Rec4x(8), Rec4x(157), Rec4x(41)]
    recs.sort(key=lambda r: sfm._get(r, "num_reg_images"), reverse=True)
    assert [sfm._get(r, "num_reg_images") for r in recs] == [157, 41, 8]
    recs = [Rec3x(8), Rec3x(157)]
    recs.sort(key=lambda r: sfm._get(r, "num_reg_images"), reverse=True)
    assert sfm._get(recs[0], "num_reg_images") == 157


def test_matrix_from_rigid_both_shapes() -> None:
    for rigid in (Rigid4x(), Rigid3xCallable()):
        m = np.asarray(sfm._matrix(rigid))
        assert m.shape == (4, 4)
        np.testing.assert_allclose(m[:3, :3], np.eye(3))
        np.testing.assert_allclose(m[:3, 3], [1.0, 2.0, 3.0])


def test_model_name_is_plain_string() -> None:
    assert sfm._model_name(FakeCam4x()) == "SIMPLE_RADIAL"


def test_focal_and_principal() -> None:
    cam = FakeCam4x()
    assert sfm._focal(cam, 0) == 1500.0
    assert sfm._principal(cam, 1) == 450.0


def test_as_list_dict_and_sequence() -> None:
    assert sfm._as_list({2: "b", 0: "a"}) == ["b", "a"]
    assert sfm._as_list(["a", "b"]) == ["a", "b"]


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok   {t.__name__}")
    print(f"OK: {len(tests)} sfm API-shape tests passed")


if __name__ == "__main__":
    main()
