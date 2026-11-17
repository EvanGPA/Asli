# Asli food analysis engine

Turns one meal (a photo, a text description, or both) into dishes, portions and macros for
Indian food. A Claude model recognizes the dishes; all nutrient numbers come from the
Indian Nutrient Databank (INDB). Design: `docs/superpowers/specs/2026-11-17-asli-food-engine-design.md`.

## Setup

```bash
uv sync
./scripts/download_indb.sh
uv run python -m asli.importer data/raw/INDB.xlsx --aliases data/aliases.csv --out data/asli_food.sqlite
```

The INDB repository has no licence file, so the raw data and the built database are not
committed. Get written permission from the INDB authors before any commercial use.

## Run the API

```bash
uv run uvicorn asli.api:app --reload
```

```bash
curl -F "text=2 rotis and a bowl of rajma" http://127.0.0.1:8000/analyze
```

```bash
curl -F "image=@meal.jpg;type=image/jpeg" http://127.0.0.1:8000/analyze
```

Settings (environment variables): `ASLI_MODEL` (default `claude-opus-5-5`), `ASLI_DATA_DIR`,
`ASLI_FOOD_DB`, `ASLI_UNMATCHED_DB`, `ASLI_HOUSEHOLD_UNITS`, `ASLI_AUTO_ACCEPT_SCORE` (90),
`ASLI_CONFIRM_SCORE` (60).

## Tests

```bash
uv run pytest
```

Live tests call the real Claude API and cost money:

```bash
ASLI_LIVE=1 uv run pytest -m live -v
```

## Accuracy

Photograph and weigh real meals, record them in `eval/meals.jsonl` (format in
`eval/meals.example.jsonl`), then run (calls the real API):

```bash
uv run python -m asli.evaluate eval/meals.jsonl
```

Rows marked PROVISIONAL in `data/household_units.csv` should be replaced with the team's own
measurements. The most frequent unmatched dishes are in `data/unmatched.sqlite`; add them to
`data/aliases.csv` and re-run the importer.
