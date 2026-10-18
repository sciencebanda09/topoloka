# pipeline — reconstruction pipeline

Turns a phone capture (video + optional sensor logs) into the artifact bundle the
web app consumes: poses, point cloud, floor/walkable map, POIs, and a Gaussian
splat.

## Layout

```
pipeline/
  namma/            python package (all stages)
    frames.py       video -> picked frames (Laplacian-sharpest per window)
    cli.py          `python -m namma.cli <stage>` entry point
    ...
  runs/             per-capture working dirs (gitignored)
```

## Quickstart

```powershell
# from pipeline/
..\.venv\Scripts\python -m namma.cli frames <video.mp4> runs/<capture>/frames --stride 6
```

Stages (built progressively):

| Stage    | Status | GPU | Description                                    |
|----------|--------|-----|------------------------------------------------|
| frames   | WIP    | no  | pick + extract frames, blur QA                 |
| sfm      | todo   | no  | pycolmap sparse reconstruction + quality gates |
| geometry | todo   | no  | floor RANSAC, gravity align, 2.5D costmap      |
| nav      | todo   | no  | A* + path smoothing on the costmap             |
| depth    | todo   | yes | Depth Anything V2 metric depth                 |
| splat    | todo   | yes | 3DGS training (gsplat)                         |
| poi      | todo   | yes | open-voctab detection + CLIP embeddings        |
| export   | todo   | no  | bundle: nav.json, poi.json, report.json, trust |
