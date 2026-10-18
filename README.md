# gutshackathon

## Setup

1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
2. Install Python 3.13: `uv python install 3.13`
3. Install dependencies: `uv sync`

## Run

`uv run main.py`

Your total score starts at 0 and is shown during each minigame. At the end of a minigame, you earn 200–1,000 points based on its failure meter, with larger penalties softened so most rounds award at least 500. The result screen shows the previous total, the round's points, then the updated total.

## Employee record

Each playthrough starts a new employee record. The onboarding flow can save a confirmed badge photo and the actual first completed agreement signature. Pen-up gaps are retained, and both keepsakes appear on the existing final review, including when the day ends after three strikes. Missing keepsakes use placeholders, and failed file writes fall back to in-memory data for the current run.

The files remain on the local computer and are never written inside this repository:

- macOS: `~/Library/Application Support/InternSurvival/runs/`
- Windows: `%LOCALAPPDATA%/InternSurvival/runs/`
- Linux: `~/.local/share/intern-survival/runs/`, or the equivalent location under `XDG_DATA_HOME`

Every run has its own folder containing `employee.json`, plus `photo.png` and `signature.png` when those keepsakes were confirmed or completed.

The clock shown between and during rounds is story time, separate from each minigame countdown. It advances from onboarding at 09:00 to the final print at 16:59 and never moves backwards when optional paperwork is inserted.
