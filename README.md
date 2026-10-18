# gutshackathon

## Setup

1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
2. Install Python 3.13: `uv python install 3.13`
3. Install dependencies: `uv sync`

## Run

`uv run main.py`

Your total score starts at 0 and is shown during each minigame. At the end of a minigame, you earn 200–1,000 points based on its failure meter, with larger penalties softened so most rounds award at least 500. The result screen shows the previous total, the round's points, then the updated total.

## Your employee record

Onboarding offers a badge photo: pinch to start a three-second countdown, then pinch to use the picture. Click **Retake** to try again or **Skip photo** to continue without one. The existing camera supplies a clean still without tracking dots; no second camera is opened. Your actual first completed agreement signature is retained, including separate pen strokes, and appears with the photo on the final review. Skipping the signing round leaves a placeholder rather than inventing a signature.

Each new playthrough gets a separate local folder containing `employee.json`, `photo.png` (if taken), and `signature.png` (if signed). Nothing is uploaded. The default locations are:

- macOS: `~/Library/Application Support/InternSurvival/runs/`
- Linux: `~/.local/share/intern-survival/runs/` (or under `XDG_DATA_HOME`)
- Windows: `%LOCALAPPDATA%/InternSurvival/runs/`

Delete these folders to remove saved keepsakes. If saving fails, the current run still displays its in-memory photo and signature and the review reports that the local save was unavailable.

The workday clock shows **story time**, separate from each round's countdown: onboarding at 09:00 through printing at 16:59, with 17:00 reached when the day is completed. Extra paperwork doesn't move the clock backwards. An early three-strike ending still shows that player's final review.

## Checks

`uv run python -m unittest discover -s tests -v`

The checks cover local keepsake isolation and saving, photo confirmation/retakes, stale camera frames, workday progression, and final review rendering. Test the live webcam capture and gestures manually on the demonstration laptop.
