# Playroom — Public Indoor 3DGS Demo

Multi-zone indoor walkthrough twin built from the public Deep Blending *Playroom*
3D Gaussian Splatting capture ([`dylanebert/3dgs`](https://huggingface.co/datasets/dylanebert/3dgs),
`playroom/playroom-7k.splat`).

## Web Bundle (`web/`)
- `splat.ksplat`: 420,000 importance-ranked Gaussians compressed into bucketed KSplat format (~10.1 MB).
- `cloud.ply`: 180,000 subsampled points in the gravity-aligned metric `nav` frame (`z = 0` at floor).
- `nav.json` + `occupancy.png`: RANSAC-leveled floor costmap (66.17 m² walkable) with connected free space and loop trajectory.
- `pois.json`: 5 curated indoor points of interest (`Timber Playhouse`, `Red Activity Table`, `East Gallery Display`, `South Archway Exit`, `Northeast Corner Desk`).
- `anchors.json`: 3 QR wayfinding anchors for AR Mode relocalization.
