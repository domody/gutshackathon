# gutshackathon

## Setup

1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
2. Install Python 3.13: `uv python install 3.13`
3. Install dependencies: `uv sync`

## Run

`uv run main.py`

Your total score starts at 0 and is shown during each minigame. At the end of a minigame, you earn 200–1,000 points based on its failure meter, with larger penalties softened so most rounds award at least 500. The result screen shows the previous total, the round's points, then the updated total.
