# Topoloka — Official Techfest 2026–27 Round 2 Submission Package

This folder mirrors the organized submission bundle for **Namma Space**, Techfest 2026–27 (IIT Bombay) — updated for **Round 2 compliance**.

---

## Google Drive Submission Structure (Round 2)

Per the official competition guidelines (`Namma_Space.docx_2_compressed.pdf`):
> *"Submit an updated Round 2 Google Drive folder ('Anyone with the link can view') containing: Updated Code Repository Link, Live Web App Link, Demonstration Video."*
> *"If your team includes additional links, live web demos, prototype access URLs, or supplementary technical documents inside your Google Drive folder, they must be neatly formatted and presented inside a single organized master PDF or Google Doc. Loose links or unorganized files inside the Drive folder will not be reviewed by judges."*

Upload ONLY the clean final files below to your Google Drive submission directory (do not leave stale R1 or AI-narrated videos in the folder):

| Filename | Deliverable Type | Description |
|---|---|---|
| **`MASTER_SUBMISSION_DOCUMENT.pdf`** | **Master Links & Supplementary PDF** | Single consolidated master PDF containing all R2 links, architecture, commercial licensing, API vs. GPU cost analysis, verification results, and raw capture video link. |
| **`Technical_Abstract_Topoloka.pdf`** | **Technical Abstract & SOP (≤ 5 Pages)** | Mirror of `docs/abstract.pdf` (4 pages): Capture SOP, Apache-2.0 `DISK+LightGlue` + Depth Small + 3DGS pipeline, `home_v1` 3-room evaluation & visual showcase, license matrix, and API vs. Own GPU cost analysis. |
| **`Proof_of_Concept_Web_Viewer_Link.txt`** | **Live Web App Link (R2)** | Direct URL to the static WebGL viewer serving `home_v1`: [https://sciencebanda09.github.io/topoloka/](https://sciencebanda09.github.io/topoloka/) |
| **`Demonstration_Video_Link.txt`** | **Own-Voice R2 Demo Video (3–5 min)** | Public link to the **human-narrated** 1080p30 video covering technical approach + 3D walkthrough of `home_v1`, plus the raw capture video (`home_v1_raw_full.mp4`). |
| **`Code_Repository_Link.txt`** | **Updated Code Repository Link** | Public MIT GitHub repository link with reproducible setup and committed `test/home_v1/` bundle (`17.12 MB`). |

## Before Final Upload (Only 3 User Actions Remaining)

1. Upload the raw capture video (`kaggle/staging/raw_captures/home_v1_raw_full.mp4`, `50.3 MB`) publicly to Google Drive ("Anyone with the link can view").
2. Record your own-voice 3–5 min narration (`docs/demo/NARRATION_SCRIPT.md`) over a 1080p walkthrough of live `home_v1`, mux via `python docs/demo/mux_submission_video.py`, and upload the final MP4 publicly.
3. Paste those 2 video URLs into `docs/abstract.md`, `capture/SOP.md`, `docs/MASTER_SUBMISSION_DOCUMENT.md`, `submission/MASTER_SUBMISSION_DOCUMENT.md`, and `submission/Demonstration_Video_Link.txt`, rebuild PDFs via `python tools/build_pdf.py`, upload `submission/` to Google Drive, and test **every single link** in an **Incognito browser window** before **30 Nov 2026**.
