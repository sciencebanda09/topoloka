# Guildhall MVS photo mesh

This sample rebuilds the Guildhall walk-through as a dense, photo-textured
triangle mesh. COLMAP's PatchMatch stereo and geometric-consistency pass
produce depth maps; the pipeline fuses them into a dense cloud, reconstructs a
surface, and assigns each face a sharp captured view. All reconstruction runs
on Kaggle.

The sample keeps the earlier Gaussian splat and point cloud alongside the
mesh. It remains in the repository for pipeline reference and is not published
on the hosted viewer, which currently serves Melbourne Metro only.

Use W/S to walk forward or backward and A/D to sidestep around objects. Arrow
keys work as well; on touchscreens, drag the left thumb sideways to sidestep.

The dense reconstruction fused 5,518,929 points into a 650,000-face mesh.
Camera visibility and depth checks assign sharp source views to 89.54% of the
faces. The bundle keeps the original capture navigation map (23.4 m²) because
the dense cloud did not provide a stable horizontal floor fit; the mesh itself
is aligned to that existing map.

Source: *Guildhall City of London England interior walkaround video* by
Acabashi, Wikimedia Commons. The source is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); see `LICENSE`
for attribution and terms. The derived sample is distributed under the same
license.

`mesh_report.json` records the mesh and texturing measurements, and
`nav_report.json` records the retained-navigation fallback. `capture_qa.json`
describes the source capture quality. `SOURCE.md` describes the model
representations included in the bundle.

Moving people can be incomplete or leave artifacts because the source is a
single moving-camera video. The static hall and sculptures are reconstructed
from the consistent multi-view observations.
