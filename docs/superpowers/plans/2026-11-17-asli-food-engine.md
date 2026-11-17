# Asli Food Analysis Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python web service that turns one meal (photo and/or text) into per-dish portions and macros for Indian food, using an AI model for recognition and the Indian Nutrient Databank for the numbers.

**Architecture:** A pipeline of small units: recognizer (Claude API, structured output) → matcher (fuzzy search over the databank, AI picks among candidates when unsure) → portion converter (household units to grams) → calculator (nutrients with low/high ranges). An `Engine` wires them together, and a FastAPI app exposes `POST /analyze`. The AI model never produces nutrient numbers.

**Tech Stack:** Python 3.12, uv, FastAPI, Pydantic v2, rapidfuzz, openpyxl, SQLite (stdlib), Anthropic Python SDK, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-asli-food-engine-design.md`

## Global Constraints

- Python `>=3.12`, managed with `uv`. Run everything through `uv run`.
- The AI model never returns nutrient values; all nutrients come from the databank (spec section 3).
- Default model `claude-opus-5-5`, overridable with `ASLI_MODEL`. Requests go through `client.beta.messages.create` with `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`.
- The Anthropic client retries once (`max_retries=1`), then the engine returns status `error` (spec 5.1).
- Images are never written to disk (spec section 6).
- Confidence ranges: high ±15%, medium ±30%, low ±50% of grams (spec 4.5).
- Match thresholds: auto-accept at fuzzy score ≥ 90; after an AI choice, `needs_confirmation` when the chosen entry scored < 60 (spec section 9).
- Portion rule exactly as spec 4.4 rules 1–4.
- Do not commit `data/raw/` or any `*.sqlite` file (spec section 9).
- Unit tests never call the real API. Live tests are marked `live` and run only with `ASLI_LIVE=1`.

## File Structure

```
pyproject.toml              project, dependencies, pytest config
.gitignore
README.md                   how to set up, import data, run, test
scripts/download_indb.sh    fetches the databank spreadsheet into data/raw/
data/aliases.csv            alternative dish names -> databank codes (committed)
data/household_units.csv    household unit -> grams, with source per row (committed)
eval/meals.example.jsonl    format example for the weighed evaluation set
src/asli/__init__.py
src/asli/models.py          shared Pydantic types and enums
src/asli/importer.py        builds the SQLite food database from INDB.xlsx
src/asli/food_db.py         loads the food database, fuzzy name search
src/asli/portions.py        household units -> grams (spec 4.4)
src/asli/calculator.py      nutrients and low/high ranges (spec 4.5)
src/asli/interfaces.py      Recognizer / CandidateChooser protocols, RecognizerError
src/asli/matcher.py         dish guess -> databank entry (spec 4.3)
src/asli/recognizer.py      ClaudeRecognizer: recognize + choose via Claude API
src/asli/unmatched_log.py   counts unmatched dish names (spec 5.2)
src/asli/config.py          settings from environment variables
src/asli/engine.py          Engine.analyze orchestration + build_engine
src/asli/api.py             FastAPI app: POST /analyze, GET /health
src/asli/evaluate.py        scoring against the weighed evaluation set
tests/conftest.py           tiny databank fixture
tests/fakes.py              fake Anthropic client, fake chooser, fake recognizer
tests/fixtures/responses/   saved AI responses replayed in tests
tests/test_*.py             one test file per module
tests/live/test_live_claude.py  on-demand tests against the real API
```

---

### Task 1: Project setup and shared types

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/asli/__init__.py`, `src/asli/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (in `asli.models`):
  - `PortionUnit(str, Enum)`: `SERVING="serving"`, `BOWL="bowl"`, `PLATE="plate"`, `PIECE="piece"`, `CUP="cup"`, `GLASS="glass"`, `TABLESPOON="tablespoon"`, `TEASPOON="teaspoon"`
  - `Confidence(str, Enum)`: `HIGH`, `MEDIUM`, `LOW` with method `lowered() -> Confidence`
  - `RecognitionStatus(str, Enum)`: `OK="ok"`, `NO_FOOD="no_food"`, `UNCLEAR_IMAGE="unclear_image"`
  - `AnalysisStatus(str, Enum)`: `OK`, `NO_FOOD`, `UNCLEAR_IMAGE`, `ERROR="error"`
  - `DishGuess(name: str, alternative_names: list[str], unit: PortionUnit, quantity: float > 0, confidence: Confidence)`
  - `RecognitionResult(status: RecognitionStatus, dishes: list[DishGuess])`
  - `Nutrients(energy_kcal, protein_g, carb_g, fat_g, fibre_g: float = 0)` with `scaled(factor) -> Nutrients` and `__add__`
  - `FoodEntry(code, name, serving_unit: PortionUnit, serving_grams: float | None, energy_kcal, protein_g, carb_g, fat_g, fibre_g)` (per 100 g) with `per_100g() -> Nutrients`
  - `NutrientRange(estimate: Nutrients, low: Nutrients, high: Nutrients)`
  - `Candidate(code: str, name: str)`
  - `DishStatus = Literal["matched", "needs_confirmation", "unmatched"]`
  - `AnalyzedDish(name, status: DishStatus, match: Candidate | None, candidates: list[Candidate], unit, quantity, grams: float | None, grams_low: float | None, grams_high: float | None, confidence: Confidence, nutrients: NutrientRange | None)`
  - `AnalysisResult(status: AnalysisStatus, message: str | None, dishes: list[AnalyzedDish], totals: NutrientRange | None)`

- [ ] **Step 1: Create project files**

`pyproject.toml`:

```toml
[project]
name = "asli-engine"
version = "0.1.0"
description = "Asli food analysis engine: meal photo or text to Indian-food macros"
requires-python = ">=3.12"
dependencies = [
    "anthropic",
    "fastapi",
    "python-multipart",
    "pydantic>=2",
    "rapidfuzz",
    "openpyxl",
    "uvicorn",
]

[dependency-groups]
dev = ["pytest", "httpx"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/asli"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
markers = ["live: calls the real Claude API and costs money; run with ASLI_LIVE=1"]
```

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
data/raw/
*.sqlite
```

`src/asli/__init__.py`:

```python
"""Asli food analysis engine."""
```

Run: `uv python pin 3.12 && uv sync`
Expected: creates `.venv` and `uv.lock` without errors.

- [ ] **Step 2: Write the failing test**

`tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from asli.models import Confidence, DishGuess, FoodEntry, Nutrients, PortionUnit


def test_confidence_lowered_steps_down_and_stops_at_low():
    assert Confidence.HIGH.lowered() is Confidence.MEDIUM
    assert Confidence.MEDIUM.lowered() is Confidence.LOW
    assert Confidence.LOW.lowered() is Confidence.LOW


def test_nutrients_add_and_scale():
    a = Nutrients(energy_kcal=100, protein_g=4, carb_g=10, fat_g=2, fibre_g=1)
    b = Nutrients(energy_kcal=50, protein_g=1, carb_g=5, fat_g=1, fibre_g=0)
    total = a + b
    assert total.protein_g == 5
    assert total.energy_kcal == 150
    assert a.scaled(0.5).carb_g == 5


def test_dish_guess_rejects_non_positive_quantity():
    with pytest.raises(ValidationError):
        DishGuess(name="dal", unit="bowl", quantity=0, confidence="high")


def test_food_entry_per_100g():
    entry = FoodEntry(
        code="X1", name="Test", serving_unit=PortionUnit.BOWL, serving_grams=150,
        energy_kcal=120, protein_g=6, carb_g=15, fat_g=4, fibre_g=5,
    )
    assert entry.per_100g() == Nutrients(energy_kcal=120, protein_g=6, carb_g=15, fat_g=4, fibre_g=5)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.models'`

- [ ] **Step 4: Write the implementation**

`src/asli/models.py`:

```python
"""Shared types for the Asli engine."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class PortionUnit(str, Enum):
    SERVING = "serving"
    BOWL = "bowl"
    PLATE = "plate"
    PIECE = "piece"
    CUP = "cup"
    GLASS = "glass"
    TABLESPOON = "tablespoon"
    TEASPOON = "teaspoon"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def lowered(self) -> "Confidence":
        if self is Confidence.HIGH:
            return Confidence.MEDIUM
        return Confidence.LOW


class RecognitionStatus(str, Enum):
    OK = "ok"
    NO_FOOD = "no_food"
    UNCLEAR_IMAGE = "unclear_image"


class AnalysisStatus(str, Enum):
    OK = "ok"
    NO_FOOD = "no_food"
    UNCLEAR_IMAGE = "unclear_image"
    ERROR = "error"


class DishGuess(BaseModel):
    """One dish as the recognizer saw it, before matching to the databank."""

    name: str
    alternative_names: list[str] = []
    unit: PortionUnit
    quantity: float = Field(gt=0)
    confidence: Confidence


class RecognitionResult(BaseModel):
    status: RecognitionStatus
    dishes: list[DishGuess] = []


class Nutrients(BaseModel):
    energy_kcal: float = 0.0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0
    fibre_g: float = 0.0

    def scaled(self, factor: float) -> "Nutrients":
        return Nutrients(**{k: v * factor for k, v in self.model_dump().items()})

    def __add__(self, other: "Nutrients") -> "Nutrients":
        a, b = self.model_dump(), other.model_dump()
        return Nutrients(**{k: a[k] + b[k] for k in a})


class FoodEntry(BaseModel):
    """One databank dish. Nutrient fields are per 100 g."""

    code: str
    name: str
    serving_unit: PortionUnit
    serving_grams: float | None
    energy_kcal: float
    protein_g: float
    carb_g: float
    fat_g: float
    fibre_g: float

    def per_100g(self) -> Nutrients:
        return Nutrients(
            energy_kcal=self.energy_kcal,
            protein_g=self.protein_g,
            carb_g=self.carb_g,
            fat_g=self.fat_g,
            fibre_g=self.fibre_g,
        )


class NutrientRange(BaseModel):
    estimate: Nutrients
    low: Nutrients
    high: Nutrients


class Candidate(BaseModel):
    code: str
    name: str


DishStatus = Literal["matched", "needs_confirmation", "unmatched"]


class AnalyzedDish(BaseModel):
    name: str
    status: DishStatus
    match: Candidate | None = None
    candidates: list[Candidate] = []
    unit: PortionUnit
    quantity: float
    grams: float | None = None
    grams_low: float | None = None
    grams_high: float | None = None
    confidence: Confidence
    nutrients: NutrientRange | None = None


class AnalysisResult(BaseModel):
    status: AnalysisStatus
    message: str | None = None
    dishes: list[AnalyzedDish] = []
    totals: NutrientRange | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore src/asli/__init__.py src/asli/models.py tests/test_models.py
git commit -m "feat: project setup and shared engine types"
```

---

### Task 2: Databank importer and food database

**Files:**
- Create: `src/asli/importer.py`, `src/asli/food_db.py`, `tests/conftest.py`
- Test: `tests/test_food_db.py`

**Interfaces:**
- Consumes: `PortionUnit`, `FoodEntry` from Task 1.
- Produces:
  - `asli.importer.canonical_unit(raw: str | None) -> PortionUnit`
  - `asli.importer.name_variants(name: str) -> list[str]`
  - `asli.importer.build_db(indb_xlsx: Path, aliases_csv: Path | None, out: Path) -> int` (returns number of foods imported; raises `ValueError` for an alias pointing to an unknown code)
  - CLI: `python -m asli.importer <INDB.xlsx> --aliases <csv> --out <sqlite>`
  - `asli.food_db.FoodDB(path)` (raises `FileNotFoundError` if missing) with `get(code: str) -> FoodEntry | None` and `search_many(queries: list[str], limit: int = 5, min_score: float = 40.0) -> list[tuple[FoodEntry, float]]` sorted by score descending, scores 0–100
  - Test fixtures `indb_xlsx` (path to a 4-row INDB-shaped workbook) and `food_db` (a `FoodDB` built from it with aliases `roti -> ASC096`, `rajma -> ASC165`)

Background: the real `INDB.xlsx` (sheet "Nutrient Data") has columns including `food_code`, `food_name`, `servings_unit`, `energy_kcal`, `protein_g`, `carb_g`, `fat_g`, `fibre_g` (per 100 g) and `unit_serving_energy_kcal`, `unit_serving_protein_g` (per serving). Serving weight in grams is not given directly; derive it as `unit_serving_energy_kcal / energy_kcal * 100`, falling back to the protein ratio. Raw serving units include `bowl`, `small bowl`, `curry bowl`, `plate`, `chapati`, `idli`, `dosa`, `tea cup`, `tall glass`, `tablespoon` and empty.

- [ ] **Step 1: Write the test fixture**

`tests/conftest.py`:

```python
"""Shared fixtures. The numbers below are test data, not real nutrition values."""

from pathlib import Path

import openpyxl
import pytest

from asli.food_db import FoodDB
from asli.importer import build_db

HEADER = [
    "food_code", "food_name", "servings_unit", "energy_kcal", "protein_g", "carb_g",
    "fat_g", "fibre_g", "unit_serving_energy_kcal", "unit_serving_protein_g",
]
ROWS = [
    # 250 kcal/100 g, 90 kcal per serving -> 36 g per chapati
    ["ASC096", "Chapati/Roti", "chapati", 250.0, 8.0, 45.0, 4.0, 5.0, 90.0, 2.88],
    # 120 kcal/100 g, 144 kcal per serving -> 120 g per bowl
    ["ASC165", "Kidney bean curry (Rajmah curry)", "bowl", 120.0, 6.0, 15.0, 4.0, 5.0, 144.0, 7.2],
    ["BFP269", "Okra/Lady's fingers fry (Bhindi sabzi/sabji/subji)", "bowl", 100.0, 2.0, 8.0, 6.0, 4.0, 166.0, 3.32],
    # no serving information
    ["ASC388", "Curd dip", None, 80.0, 5.0, 6.0, 4.0, 0.0, None, None],
]


@pytest.fixture
def indb_xlsx(tmp_path: Path) -> Path:
    path = tmp_path / "INDB.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nutrient Data"
    ws.append(HEADER)
    for row in ROWS:
        ws.append(row)
    wb.save(path)
    return path


@pytest.fixture
def food_db(tmp_path: Path, indb_xlsx: Path) -> FoodDB:
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("alias,food_code\nroti,ASC096\nrajma,ASC165\n", encoding="utf-8")
    out = tmp_path / "food.sqlite"
    build_db(indb_xlsx, aliases, out)
    return FoodDB(out)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_food_db.py`:

```python
import pytest

from asli.food_db import FoodDB
from asli.importer import build_db, canonical_unit, name_variants
from asli.models import PortionUnit


def test_imports_rows(food_db):
    assert food_db.get("ASC096").name == "Chapati/Roti"
    assert food_db.get("NOPE") is None


def test_serving_grams_derived_from_energy_ratio(food_db):
    assert food_db.get("ASC096").serving_grams == pytest.approx(36.0)
    assert food_db.get("ASC165").serving_grams == pytest.approx(120.0)


def test_missing_serving_information_gives_none(food_db):
    entry = food_db.get("ASC388")
    assert entry.serving_grams is None
    assert entry.serving_unit is PortionUnit.SERVING


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("bowl", PortionUnit.BOWL),
        ("small bowl", PortionUnit.BOWL),
        ("curry bowl", PortionUnit.BOWL),
        ("plate", PortionUnit.PLATE),
        ("tea cup", PortionUnit.CUP),
        ("tall glass", PortionUnit.GLASS),
        ("tablespoon", PortionUnit.TABLESPOON),
        ("chapati", PortionUnit.PIECE),
        ("idli", PortionUnit.PIECE),
        (None, PortionUnit.SERVING),
        ("  ", PortionUnit.SERVING),
    ],
)
def test_canonical_unit(raw, expected):
    assert canonical_unit(raw) is expected


def test_name_variants_split_parentheses():
    assert name_variants("Kidney bean curry (Rajmah curry)") == [
        "Kidney bean curry (Rajmah curry)", "Kidney bean curry", "Rajmah curry",
    ]
    assert name_variants("Curd dip") == ["Curd dip"]


def test_alias_exact_match_scores_100(food_db):
    entry, score = food_db.search_many(["roti"])[0]
    assert entry.code == "ASC096"
    assert score == 100


def test_search_finds_parenthetical_name(food_db):
    entry, _ = food_db.search_many(["rajmah curry"])[0]
    assert entry.code == "ASC165"


def test_search_merges_queries_and_keeps_best_score(food_db):
    results = food_db.search_many(["something else", "rajma"])
    assert results[0][0].code == "ASC165"
    assert results[0][1] == 100


def test_search_drops_poor_matches(food_db):
    assert food_db.search_many(["zzzzqqqq"]) == []


def test_unknown_alias_code_rejected(tmp_path, indb_xlsx):
    aliases = tmp_path / "bad.csv"
    aliases.write_text("alias,food_code\nchole,NOPE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="NOPE"):
        build_db(indb_xlsx, aliases, tmp_path / "x.sqlite")


def test_missing_database_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="asli.importer"):
        FoodDB(tmp_path / "missing.sqlite")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_food_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.food_db'`

- [ ] **Step 4: Write the importer**

`src/asli/importer.py`:

```python
"""Build the Asli food database (SQLite) from the Indian Nutrient Databank spreadsheet."""

import argparse
import csv
import re
import sqlite3
from pathlib import Path

import openpyxl

from .models import PortionUnit

_UNIT_MAP = {
    "bowl": PortionUnit.BOWL,
    "small bowl": PortionUnit.BOWL,
    "soup bowl": PortionUnit.BOWL,
    "curry bowl": PortionUnit.BOWL,
    "katori": PortionUnit.BOWL,
    "plate": PortionUnit.PLATE,
    "small plate": PortionUnit.PLATE,
    "dish": PortionUnit.PLATE,
    "shallow dish": PortionUnit.PLATE,
    "cup": PortionUnit.CUP,
    "tea cup": PortionUnit.CUP,
    "glass": PortionUnit.GLASS,
    "tall glass": PortionUnit.GLASS,
    "tablespoon": PortionUnit.TABLESPOON,
    "teaspoon": PortionUnit.TEASPOON,
    "serving": PortionUnit.SERVING,
}

_SCHEMA = """
CREATE TABLE foods (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    serving_unit TEXT NOT NULL,
    serving_grams REAL,
    energy_kcal REAL NOT NULL,
    protein_g REAL NOT NULL,
    carb_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    fibre_g REAL NOT NULL
);
CREATE TABLE names (
    text TEXT NOT NULL,
    code TEXT NOT NULL REFERENCES foods(code)
);
"""


def canonical_unit(raw: str | None) -> PortionUnit:
    """Map an INDB serving unit to our units. Unknown non-empty units are countable items."""
    if raw is None or not str(raw).strip():
        return PortionUnit.SERVING
    return _UNIT_MAP.get(str(raw).strip().lower(), PortionUnit.PIECE)


def name_variants(name: str) -> list[str]:
    """The full name, the name without parentheses, and each parenthetical part."""
    variants = [name]
    base = re.sub(r"\([^)]*\)", "", name).strip()
    variants.append(base)
    variants.extend(part.strip() for part in re.findall(r"\(([^)]*)\)", name))
    return [v for v in dict.fromkeys(variants) if v]


def _number(row: tuple, col: dict[str, int], key: str) -> float | None:
    if key not in col:
        return None
    value = row[col[key]]
    if value is None or value == "":
        return None
    return float(value)


def _serving_grams(row: tuple, col: dict[str, int]) -> float | None:
    for per_100g_key, per_serving_key in (
        ("energy_kcal", "unit_serving_energy_kcal"),
        ("protein_g", "unit_serving_protein_g"),
    ):
        per_100g = _number(row, col, per_100g_key)
        per_serving = _number(row, col, per_serving_key)
        if per_100g and per_serving and per_100g > 0 and per_serving > 0:
            return per_serving / per_100g * 100
    return None


def build_db(indb_xlsx: Path, aliases_csv: Path | None, out: Path) -> int:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    workbook = openpyxl.load_workbook(indb_xlsx, read_only=True)
    rows = workbook.worksheets[0].iter_rows(values_only=True)
    header = [str(h) if h is not None else "" for h in next(rows)]
    col = {name: i for i, name in enumerate(header)}

    conn = sqlite3.connect(out)
    try:
        conn.executescript(_SCHEMA)
        count = 0
        for row in rows:
            code = row[col["food_code"]]
            if not code:
                continue
            name = str(row[col["food_name"]]).strip()
            conn.execute(
                "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    name,
                    canonical_unit(row[col["servings_unit"]]).value,
                    _serving_grams(row, col),
                    _number(row, col, "energy_kcal") or 0.0,
                    _number(row, col, "protein_g") or 0.0,
                    _number(row, col, "carb_g") or 0.0,
                    _number(row, col, "fat_g") or 0.0,
                    _number(row, col, "fibre_g") or 0.0,
                ),
            )
            for variant in name_variants(name):
                conn.execute("INSERT INTO names VALUES (?, ?)", (variant, code))
            count += 1

        if aliases_csv is not None:
            with open(aliases_csv, newline="", encoding="utf-8") as f:
                for alias_row in csv.DictReader(f):
                    alias = alias_row["alias"].strip()
                    code = alias_row["food_code"].strip()
                    if conn.execute("SELECT 1 FROM foods WHERE code = ?", (code,)).fetchone() is None:
                        raise ValueError(f"Alias {alias!r} points to unknown food code {code}")
                    conn.execute("INSERT INTO names VALUES (?, ?)", (alias, code))
        conn.commit()
    finally:
        conn.close()
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the Asli food database from INDB.xlsx")
    parser.add_argument("indb_xlsx", type=Path)
    parser.add_argument("--aliases", type=Path, default=Path("data/aliases.csv"))
    parser.add_argument("--out", type=Path, default=Path("data/asli_food.sqlite"))
    args = parser.parse_args(argv)
    count = build_db(args.indb_xlsx, args.aliases, args.out)
    print(f"Imported {count} foods into {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Write the food database**

`src/asli/food_db.py`:

```python
"""Read-only access to the Asli food database, with fuzzy name search."""

import sqlite3
from pathlib import Path

from rapidfuzz import fuzz, process, utils

from .models import FoodEntry, PortionUnit


class FoodDB:
    def __init__(self, path: str | Path):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Food database not found at {path}. Build it with: uv run python -m asli.importer"
            )
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            self._entries = {
                row["code"]: _to_entry(row) for row in conn.execute("SELECT * FROM foods")
            }
            self._names = [(row["text"], row["code"]) for row in conn.execute("SELECT text, code FROM names")]
        finally:
            conn.close()
        self._choices = [text for text, _ in self._names]

    def get(self, code: str) -> FoodEntry | None:
        return self._entries.get(code)

    def search_many(
        self, queries: list[str], limit: int = 5, min_score: float = 40.0
    ) -> list[tuple[FoodEntry, float]]:
        """Best entries for any of the queries, one result per food, highest score first."""
        best: dict[str, float] = {}
        for query in queries:
            if not query or not query.strip():
                continue
            hits = process.extract(
                query,
                self._choices,
                scorer=fuzz.token_sort_ratio,
                processor=utils.default_process,
                limit=limit * 4,
                score_cutoff=min_score,
            )
            for _text, score, index in hits:
                code = self._names[index][1]
                if score > best.get(code, -1.0):
                    best[code] = score
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [(self._entries[code], score) for code, score in ranked]


def _to_entry(row: sqlite3.Row) -> FoodEntry:
    return FoodEntry(
        code=row["code"],
        name=row["name"],
        serving_unit=PortionUnit(row["serving_unit"]),
        serving_grams=row["serving_grams"],
        energy_kcal=row["energy_kcal"],
        protein_g=row["protein_g"],
        carb_g=row["carb_g"],
        fat_g=row["fat_g"],
        fibre_g=row["fibre_g"],
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_food_db.py -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/asli/importer.py src/asli/food_db.py tests/conftest.py tests/test_food_db.py
git commit -m "feat: import the Indian Nutrient Databank and search dish names"
```

---

### Task 3: Portion converter

**Files:**
- Create: `src/asli/portions.py`, `data/household_units.csv`
- Test: `tests/test_portions.py`

**Interfaces:**
- Consumes: `PortionUnit`, `FoodEntry` from Task 1.
- Produces:
  - `asli.portions.DEFAULT_GRAMS = 100.0`
  - `asli.portions.Portion(grams: float, reduced_confidence: bool)` (frozen dataclass)
  - `asli.portions.load_household_units(path: str | Path) -> dict[PortionUnit, float]`
  - `asli.portions.to_grams(unit: PortionUnit, quantity: float, entry: FoodEntry, household: dict[PortionUnit, float]) -> Portion`

- [ ] **Step 1: Create the household units table**

`data/household_units.csv`:

```csv
unit,grams,source
bowl,150,PROVISIONAL: replace with team measurement of a standard katori of cooked food
plate,300,INDB serving size for boiled rice (ASC113) is 1 plate = 300 g; PROVISIONAL for other dishes
cup,240,INDB Units.xlsx: 1 cup = 240 g
glass,200,INDB Units.xlsx: 1 glass of water = 200 ml; PROVISIONAL density 1 g/ml
tablespoon,15,Standard measure 1 tbsp = 15 ml; PROVISIONAL density 1 g/ml
teaspoon,5,Standard measure 1 tsp = 5 ml; PROVISIONAL density 1 g/ml
```

- [ ] **Step 2: Write the failing tests**

`tests/test_portions.py`:

```python
from pathlib import Path

import pytest

from asli.models import FoodEntry, PortionUnit
from asli.portions import DEFAULT_GRAMS, load_household_units, to_grams

HOUSEHOLD = {PortionUnit.BOWL: 150.0, PortionUnit.GLASS: 200.0}
REPO_ROOT = Path(__file__).resolve().parents[1]


def entry(serving_unit: PortionUnit, serving_grams: float | None) -> FoodEntry:
    return FoodEntry(
        code="X1", name="Test dish", serving_unit=serving_unit, serving_grams=serving_grams,
        energy_kcal=100, protein_g=5, carb_g=10, fat_g=3, fibre_g=2,
    )


def test_household_unit_uses_table_even_when_dish_has_serving_weight():
    portion = to_grams(PortionUnit.BOWL, 2, entry(PortionUnit.BOWL, 701.0), HOUSEHOLD)
    assert portion.grams == 300.0
    assert portion.reduced_confidence is False


def test_piece_of_countable_dish_uses_per_piece_weight():
    portion = to_grams(PortionUnit.PIECE, 2, entry(PortionUnit.PIECE, 36.0), HOUSEHOLD)
    assert portion.grams == 72.0
    assert portion.reduced_confidence is False


def test_serving_uses_databank_serving_weight():
    portion = to_grams(PortionUnit.SERVING, 1.5, entry(PortionUnit.BOWL, 120.0), HOUSEHOLD)
    assert portion.grams == pytest.approx(180.0)
    assert portion.reduced_confidence is False


def test_piece_of_non_countable_dish_falls_back_with_reduced_confidence():
    portion = to_grams(PortionUnit.PIECE, 1, entry(PortionUnit.BOWL, 120.0), HOUSEHOLD)
    assert portion.grams == 120.0
    assert portion.reduced_confidence is True


def test_unit_missing_from_table_falls_back_to_serving_weight():
    portion = to_grams(PortionUnit.PLATE, 1, entry(PortionUnit.PLATE, 300.0), HOUSEHOLD)
    assert portion.grams == 300.0
    assert portion.reduced_confidence is True


def test_no_serving_weight_uses_default_with_reduced_confidence():
    portion = to_grams(PortionUnit.SERVING, 2, entry(PortionUnit.SERVING, None), HOUSEHOLD)
    assert portion.grams == 2 * DEFAULT_GRAMS
    assert portion.reduced_confidence is True


def test_load_household_units_reads_committed_table():
    table = load_household_units(REPO_ROOT / "data" / "household_units.csv")
    assert table[PortionUnit.BOWL] == 150.0
    assert table[PortionUnit.CUP] == 240.0
    assert set(table) == {
        PortionUnit.BOWL, PortionUnit.PLATE, PortionUnit.CUP,
        PortionUnit.GLASS, PortionUnit.TABLESPOON, PortionUnit.TEASPOON,
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_portions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.portions'`

- [ ] **Step 4: Write the implementation**

`src/asli/portions.py`:

```python
"""Household units to grams (spec 4.4)."""

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import FoodEntry, PortionUnit

DEFAULT_GRAMS = 100.0


@dataclass(frozen=True)
class Portion:
    grams: float
    reduced_confidence: bool


def load_household_units(path: str | Path) -> dict[PortionUnit, float]:
    with open(path, newline="", encoding="utf-8") as f:
        return {PortionUnit(row["unit"]): float(row["grams"]) for row in csv.DictReader(f)}


def to_grams(
    unit: PortionUnit, quantity: float, entry: FoodEntry, household: dict[PortionUnit, float]
) -> Portion:
    # Rule 1: containers and spoons use the household table.
    if unit in household:
        return Portion(quantity * household[unit], reduced_confidence=False)
    if entry.serving_grams:
        # Rules 2 and 3: per-piece weight for countable dishes, serving weight for "serving".
        exact = unit == PortionUnit.SERVING or (
            unit == PortionUnit.PIECE and entry.serving_unit == PortionUnit.PIECE
        )
        # Rule 4: any other combination uses the serving weight with reduced confidence.
        return Portion(quantity * entry.serving_grams, reduced_confidence=not exact)
    return Portion(quantity * DEFAULT_GRAMS, reduced_confidence=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_portions.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/asli/portions.py data/household_units.csv tests/test_portions.py
git commit -m "feat: convert household portions to grams"
```

---

### Task 4: Nutrient calculator

**Files:**
- Create: `src/asli/calculator.py`
- Test: `tests/test_calculator.py`

**Interfaces:**
- Consumes: `Confidence`, `FoodEntry`, `Nutrients`, `NutrientRange` from Task 1.
- Produces:
  - `asli.calculator.RANGE_FRACTION: dict[Confidence, float]` = high 0.15, medium 0.30, low 0.50
  - `asli.calculator.DishNutrition(grams_low: float, grams_high: float, nutrients: NutrientRange)` (frozen dataclass)
  - `asli.calculator.nutrients_for(entry: FoodEntry, grams: float) -> Nutrients`
  - `asli.calculator.dish_nutrition(entry: FoodEntry, grams: float, confidence: Confidence) -> DishNutrition`
  - `asli.calculator.total(ranges: list[NutrientRange]) -> NutrientRange` (all zeros for an empty list)

- [ ] **Step 1: Write the failing tests**

`tests/test_calculator.py`:

```python
import pytest

from asli.calculator import dish_nutrition, nutrients_for, total
from asli.models import Confidence, FoodEntry, Nutrients, NutrientRange, PortionUnit

CHAPATI = FoodEntry(
    code="ASC096", name="Chapati/Roti", serving_unit=PortionUnit.PIECE, serving_grams=36.0,
    energy_kcal=250, protein_g=8, carb_g=45, fat_g=4, fibre_g=5,
)


def test_nutrients_scale_with_grams():
    n = nutrients_for(CHAPATI, 36.0)
    assert n.protein_g == pytest.approx(2.88)
    assert n.energy_kcal == pytest.approx(90.0)


@pytest.mark.parametrize(
    "confidence, low_factor, high_factor",
    [(Confidence.HIGH, 0.85, 1.15), (Confidence.MEDIUM, 0.70, 1.30), (Confidence.LOW, 0.50, 1.50)],
)
def test_dish_range_widens_with_lower_confidence(confidence, low_factor, high_factor):
    result = dish_nutrition(CHAPATI, 100.0, confidence)
    assert result.grams_low == pytest.approx(100.0 * low_factor)
    assert result.grams_high == pytest.approx(100.0 * high_factor)
    assert result.nutrients.estimate.protein_g == pytest.approx(8.0)
    assert result.nutrients.low.protein_g == pytest.approx(8.0 * low_factor)
    assert result.nutrients.high.protein_g == pytest.approx(8.0 * high_factor)


def test_total_sums_each_bound():
    a = dish_nutrition(CHAPATI, 100.0, Confidence.HIGH).nutrients
    b = dish_nutrition(CHAPATI, 50.0, Confidence.LOW).nutrients
    t = total([a, b])
    assert t.estimate.protein_g == pytest.approx(8.0 + 4.0)
    assert t.low.protein_g == pytest.approx(8.0 * 0.85 + 4.0 * 0.5)
    assert t.high.protein_g == pytest.approx(8.0 * 1.15 + 4.0 * 1.5)


def test_total_of_nothing_is_zero():
    assert total([]) == NutrientRange(estimate=Nutrients(), low=Nutrients(), high=Nutrients())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_calculator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.calculator'`

- [ ] **Step 3: Write the implementation**

`src/asli/calculator.py`:

```python
"""Nutrients per dish with low/high ranges, and meal totals (spec 4.5)."""

from dataclasses import dataclass

from .models import Confidence, FoodEntry, Nutrients, NutrientRange

RANGE_FRACTION = {
    Confidence.HIGH: 0.15,
    Confidence.MEDIUM: 0.30,
    Confidence.LOW: 0.50,
}


@dataclass(frozen=True)
class DishNutrition:
    grams_low: float
    grams_high: float
    nutrients: NutrientRange


def nutrients_for(entry: FoodEntry, grams: float) -> Nutrients:
    return entry.per_100g().scaled(grams / 100.0)


def dish_nutrition(entry: FoodEntry, grams: float, confidence: Confidence) -> DishNutrition:
    fraction = RANGE_FRACTION[confidence]
    grams_low = grams * (1 - fraction)
    grams_high = grams * (1 + fraction)
    return DishNutrition(
        grams_low=grams_low,
        grams_high=grams_high,
        nutrients=NutrientRange(
            estimate=nutrients_for(entry, grams),
            low=nutrients_for(entry, grams_low),
            high=nutrients_for(entry, grams_high),
        ),
    )


def total(ranges: list[NutrientRange]) -> NutrientRange:
    result = NutrientRange(estimate=Nutrients(), low=Nutrients(), high=Nutrients())
    for r in ranges:
        result = NutrientRange(
            estimate=result.estimate + r.estimate,
            low=result.low + r.low,
            high=result.high + r.high,
        )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_calculator.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/asli/calculator.py tests/test_calculator.py
git commit -m "feat: calculate dish nutrients with confidence ranges"
```

---

### Task 5: Matcher

**Files:**
- Create: `src/asli/interfaces.py`, `src/asli/matcher.py`, `tests/fakes.py`
- Test: `tests/test_matcher.py`

**Interfaces:**
- Consumes: `FoodDB.search_many`, `FoodDB.get` (Task 2); `DishGuess`, `Candidate`, `FoodEntry`, `RecognitionResult`, `DishStatus` (Task 1); fixture `food_db` (Task 2).
- Produces:
  - `asli.interfaces.RecognizerError(Exception)`
  - `asli.interfaces.Recognizer` protocol: `recognize(image: bytes | None, media_type: str | None, text: str | None) -> RecognitionResult`
  - `asli.interfaces.CandidateChooser` protocol: `choose(guess: DishGuess, candidates: list[Candidate]) -> str | None` (a candidate code, or `None` for no match)
  - `asli.matcher.MatchResult(status: DishStatus, entry: FoodEntry | None, candidates: list[Candidate], used_chooser: bool)` (frozen dataclass)
  - `asli.matcher.Matcher(db: FoodDB, chooser: CandidateChooser, auto_accept_score: float = 90.0, confirm_below_score: float = 60.0, candidate_count: int = 5)` with `match(guess: DishGuess) -> MatchResult`
  - `tests/fakes.py`: `FakeChooser(answer)` with `.calls`; also `FakeBlock`, `FakeResponse`, `text_response`, `recorded`, `FakeClient`, `FakeRecognizer` used by Tasks 6 and 7

Behaviour (spec 4.3): search with the name and alternative names. Top score ≥ `auto_accept_score` → `matched` with no AI call. Otherwise send the top `candidate_count` entries to the chooser. Chooser answers `None` or a code not offered → `unmatched` with the top 3 candidates. Chosen entry's score < `confirm_below_score` → `needs_confirmation` with candidates = [chosen, up to 2 others]. Otherwise `matched`.

- [ ] **Step 1: Write the protocols**

`src/asli/interfaces.py`:

```python
"""Interfaces between the engine and the AI recognition step."""

from typing import Protocol

from .models import Candidate, DishGuess, RecognitionResult


class RecognizerError(Exception):
    """The AI service failed or returned something unusable."""


class Recognizer(Protocol):
    def recognize(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> RecognitionResult: ...


class CandidateChooser(Protocol):
    def choose(self, guess: DishGuess, candidates: list[Candidate]) -> str | None: ...
```

- [ ] **Step 2: Write the test fakes**

`tests/fakes.py`:

```python
"""Test doubles. Nothing here calls the network."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

FIXTURES = Path(__file__).parent / "fixtures" / "responses"


@dataclass
class FakeBlock:
    type: str
    text: str = ""


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"


def text_response(payload: dict | str, stop_reason: str = "end_turn") -> FakeResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeResponse(content=[FakeBlock("thinking"), FakeBlock("text", text)], stop_reason=stop_reason)


def recorded(name: str) -> FakeResponse:
    """Replay a saved AI response from tests/fixtures/responses/<name>.json."""
    return text_response((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeMessages:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    """Mimics anthropic.Anthropic() for client.beta.messages.create(...)."""

    def __init__(self, responses: list):
        self.messages = FakeMessages(responses)
        self.beta = SimpleNamespace(messages=self.messages)


class FakeChooser:
    def __init__(self, answer: str | None):
        self.answer = answer
        self.calls: list[tuple] = []

    def choose(self, guess, candidates):
        self.calls.append((guess, candidates))
        return self.answer


@dataclass
class FakeRecognizer:
    result: object = None
    error: Exception | None = None
    calls: list = field(default_factory=list)

    def recognize(self, image, media_type, text):
        self.calls.append((image, media_type, text))
        if self.error is not None:
            raise self.error
        return self.result
```

- [ ] **Step 3: Write the failing tests**

`tests/test_matcher.py`:

```python
from fakes import FakeChooser

from asli.matcher import Matcher
from asli.models import DishGuess


def guess(name: str, *alternatives: str) -> DishGuess:
    return DishGuess(
        name=name, alternative_names=list(alternatives), unit="bowl", quantity=1, confidence="high"
    )


def test_exact_alias_matches_without_asking_the_ai(food_db):
    chooser = FakeChooser(answer="ASC096")
    result = Matcher(food_db, chooser).match(guess("roti"))
    assert result.status == "matched"
    assert result.entry.code == "ASC096"
    assert result.used_chooser is False
    assert chooser.calls == []


def test_alternative_name_can_produce_the_match(food_db):
    result = Matcher(food_db, FakeChooser(answer=None)).match(guess("lal lobia", "rajma"))
    assert result.entry.code == "ASC165"
    assert result.status == "matched"


def test_weak_match_asks_the_ai_with_candidates(food_db):
    chooser = FakeChooser(answer="ASC165")
    matcher = Matcher(food_db, chooser, auto_accept_score=101, confirm_below_score=0)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "matched"
    assert result.entry.code == "ASC165"
    assert result.used_chooser is True
    offered = [c.code for c in chooser.calls[0][1]]
    assert "ASC165" in offered
    assert len(offered) <= 5


def test_low_scoring_ai_choice_needs_confirmation(food_db):
    matcher = Matcher(food_db, FakeChooser(answer="ASC165"), auto_accept_score=101, confirm_below_score=101)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "needs_confirmation"
    assert result.entry.code == "ASC165"
    assert result.candidates[0].code == "ASC165"
    assert 1 <= len(result.candidates) <= 3


def test_ai_says_none_gives_unmatched_with_candidates(food_db):
    matcher = Matcher(food_db, FakeChooser(answer=None), auto_accept_score=101)
    result = matcher.match(guess("kidney beans"))
    assert result.status == "unmatched"
    assert result.entry is None
    assert len(result.candidates) <= 3


def test_ai_choice_outside_candidates_is_rejected(food_db):
    matcher = Matcher(food_db, FakeChooser(answer="NOT_OFFERED"), auto_accept_score=101)
    assert matcher.match(guess("kidney beans")).status == "unmatched"


def test_no_search_hits_is_unmatched_without_ai_call(food_db):
    chooser = FakeChooser(answer="ASC096")
    result = Matcher(food_db, chooser).match(guess("zzzzqqqq"))
    assert result.status == "unmatched"
    assert chooser.calls == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_matcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.matcher'`

- [ ] **Step 5: Write the implementation**

`src/asli/matcher.py`:

```python
"""Match a recognized dish to a databank entry (spec 4.3)."""

from dataclasses import dataclass

from .food_db import FoodDB
from .interfaces import CandidateChooser
from .models import Candidate, DishGuess, DishStatus, FoodEntry


@dataclass(frozen=True)
class MatchResult:
    status: DishStatus
    entry: FoodEntry | None
    candidates: list[Candidate]
    used_chooser: bool


class Matcher:
    def __init__(
        self,
        db: FoodDB,
        chooser: CandidateChooser,
        auto_accept_score: float = 90.0,
        confirm_below_score: float = 60.0,
        candidate_count: int = 5,
    ):
        self._db = db
        self._chooser = chooser
        self._auto_accept = auto_accept_score
        self._confirm_below = confirm_below_score
        self._candidate_count = candidate_count

    def match(self, guess: DishGuess) -> MatchResult:
        hits = self._db.search_many(
            [guess.name, *guess.alternative_names], limit=self._candidate_count
        )
        if not hits:
            return MatchResult("unmatched", None, [], used_chooser=False)

        top_entry, top_score = hits[0]
        if top_score >= self._auto_accept:
            return MatchResult("matched", top_entry, [], used_chooser=False)

        candidates = [Candidate(code=e.code, name=e.name) for e, _ in hits]
        scores = {e.code: score for e, score in hits}
        chosen = self._chooser.choose(guess, candidates)
        if chosen is None or chosen not in scores:
            return MatchResult("unmatched", None, candidates[:3], used_chooser=True)

        entry = self._db.get(chosen)
        if scores[chosen] < self._confirm_below:
            others = [c for c in candidates if c.code != chosen][:2]
            return MatchResult(
                "needs_confirmation",
                entry,
                [Candidate(code=entry.code, name=entry.name), *others],
                used_chooser=True,
            )
        return MatchResult("matched", entry, [], used_chooser=True)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_matcher.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add src/asli/interfaces.py src/asli/matcher.py tests/fakes.py tests/test_matcher.py
git commit -m "feat: match recognized dishes to databank entries"
```

---

### Task 6: Claude recognizer

**Files:**
- Create: `src/asli/recognizer.py`, `tests/fixtures/responses/recognize_thali.json`, `tests/fixtures/responses/recognize_no_food.json`
- Test: `tests/test_recognizer.py`

**Interfaces:**
- Consumes: `RecognizerError` (Task 5); `DishGuess`, `RecognitionResult`, `RecognitionStatus`, `Candidate`, `PortionUnit`, `Confidence` (Task 1); `FakeClient`, `recorded`, `text_response` (Task 5).
- Produces:
  - `asli.recognizer.DEFAULT_MODEL = "claude-opus-5-5"`
  - `asli.recognizer.ClaudeRecognizer(client=None, model: str = DEFAULT_MODEL)` implementing `recognize(image, media_type, text) -> RecognitionResult` and `choose(guess, candidates) -> str | None`. When `client` is `None` it creates `anthropic.Anthropic(max_retries=1, timeout=60.0)`. Raises `RecognizerError` for API errors, refusals, cut-off responses and malformed output.

SDK facts this task relies on (from the Claude API docs): images are sent as `{"type": "image", "source": {"type": "base64", "media_type": ..., "data": <base64 str>}}`; structured output is `output_config={"format": {"type": "json_schema", "schema": ...}}` and the first `text` block is valid JSON; Claude Opus 5.5 always thinks, so the response also contains `thinking` blocks to skip, and effort goes in `output_config["effort"]`; always check `stop_reason` (`"refusal"`, `"max_tokens"`) before reading content; `anthropic.APIStatusError` and `anthropic.APIConnectionError` (which covers timeouts) are the error classes.

- [ ] **Step 1: Save the AI response fixtures**

`tests/fixtures/responses/recognize_thali.json`:

```json
{"status": "ok", "dishes": [
  {"name": "chapati", "alternative_names": ["roti"], "unit": "piece", "quantity": 2, "confidence": "high"},
  {"name": "rajma", "alternative_names": ["kidney bean curry"], "unit": "bowl", "quantity": 1, "confidence": "medium"},
  {"name": "pickle", "alternative_names": [], "unit": "teaspoon", "quantity": 0, "confidence": "low"}
]}
```

`tests/fixtures/responses/recognize_no_food.json`:

```json
{"status": "no_food", "dishes": []}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_recognizer.py`:

```python
import base64

import anthropic
import httpx
import pytest
from fakes import FakeClient, recorded, text_response

from asli.interfaces import RecognizerError
from asli.models import Candidate, DishGuess, PortionUnit, RecognitionStatus
from asli.recognizer import ClaudeRecognizer


def make(responses):
    client = FakeClient(responses)
    return ClaudeRecognizer(client=client, model="test-model"), client.messages


def test_parses_dishes_and_drops_zero_quantities():
    recognizer, _ = make([recorded("recognize_thali")])
    result = recognizer.recognize(b"img", "image/jpeg", None)
    assert result.status is RecognitionStatus.OK
    assert [d.name for d in result.dishes] == ["chapati", "rajma"]
    assert result.dishes[0].unit is PortionUnit.PIECE
    assert result.dishes[0].quantity == 2


def test_request_sends_image_schema_and_fallback():
    recognizer, messages = make([recorded("recognize_thali")])
    recognizer.recognize(b"img", "image/jpeg", "dal is toor dal")
    call = messages.calls[0]
    assert call["model"] == "test-model"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[0]["source"]["data"] == base64.standard_b64encode(b"img").decode()
    assert "toor dal" in content[1]["text"]


def test_text_only_request_has_no_image_block():
    recognizer, messages = make([recorded("recognize_thali")])
    recognizer.recognize(None, None, "2 rotis and rajma")
    content = messages.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text"]


def test_no_food_returns_no_dishes():
    recognizer, _ = make([recorded("recognize_no_food")])
    result = recognizer.recognize(b"img", "image/png", None)
    assert result.status is RecognitionStatus.NO_FOOD
    assert result.dishes == []


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_or_cut_off_raises(stop_reason):
    recognizer, _ = make([text_response({"status": "ok", "dishes": []}, stop_reason=stop_reason)])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_connection_error_raises_recognizer_error():
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    recognizer, _ = make([error])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_invalid_json_raises():
    recognizer, _ = make([text_response("not json")])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_wrong_shape_raises():
    # quantity present (so the dish is not dropped) but unit and confidence missing
    recognizer, _ = make([text_response({"status": "ok", "dishes": [{"name": "dal", "quantity": 1}]})])
    with pytest.raises(RecognizerError):
        recognizer.recognize(None, None, "dal")


def test_choose_returns_code_and_limits_answers_to_candidates():
    recognizer, messages = make([text_response({"code": "ASC165"})])
    guess = DishGuess(name="rajma", unit="bowl", quantity=1, confidence="high")
    candidates = [Candidate(code="ASC165", name="Kidney bean curry"), Candidate(code="ASC167", name="Sambar")]
    assert recognizer.choose(guess, candidates) == "ASC165"
    schema = messages.calls[0]["output_config"]["format"]["schema"]
    assert schema["properties"]["code"]["enum"] == ["ASC165", "ASC167", "none"]


def test_choose_none_means_no_match():
    recognizer, _ = make([text_response({"code": "none"})])
    guess = DishGuess(name="mystery", unit="bowl", quantity=1, confidence="low")
    assert recognizer.choose(guess, [Candidate(code="ASC165", name="Kidney bean curry")]) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_recognizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.recognizer'`

- [ ] **Step 4: Write the implementation**

`src/asli/recognizer.py`:

```python
"""Dish recognition and candidate choice using the Claude API."""

import base64
import json

import anthropic

from .interfaces import RecognizerError
from .models import (
    Candidate,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionResult,
    RecognitionStatus,
)

DEFAULT_MODEL = "claude-opus-5-5"

RECOGNIZE_SYSTEM = """You identify food in meal photos and meal descriptions for an Indian nutrition tracker.

Report each distinct dish or food item that is being eaten. Do not estimate nutrients.

For each dish give:
- name: the name most Indians would use, for example "rajma", "bhindi sabzi", "chapati".
- alternative_names: other common names, including the English name, for example ["kidney bean curry"].
- unit and quantity: how much is present, using only these units: serving, bowl (a katori), plate, piece (for countable items such as roti, idli, dosa, samosa), cup, glass, tablespoon, teaspoon. Quantity may be fractional, for example 0.5 plate.
- confidence: "high" if the dish and amount are clear, "medium" if either is uncertain, "low" if you are mostly guessing.

Set status to "no_food" if no food or drink is being eaten, "unclear_image" if the photo is too blurry, dark or cropped to tell, and "ok" otherwise. With "no_food" or "unclear_image", return an empty dishes list.

If a text description comes with a photo, use it for what the photo cannot show, such as which dal it is. If the text and the photo disagree about what is present, trust the text."""

CHOOSE_SYSTEM = """You match a dish to an entry in the Indian Nutrient Databank. You are given the dish as it was described and a list of databank entries with their codes. Answer with the code of the entry that is the same dish, or "none" if no entry is the same dish. A similar dish with different main ingredients is not the same dish."""

RECOGNITION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": [s.value for s in RecognitionStatus]},
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "alternative_names": {"type": "array", "items": {"type": "string"}},
                    "unit": {"type": "string", "enum": [u.value for u in PortionUnit]},
                    "quantity": {"type": "number"},
                    "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
                },
                "required": ["name", "alternative_names", "unit", "quantity", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "dishes"],
    "additionalProperties": False,
}


class ClaudeRecognizer:
    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        self._client = client or anthropic.Anthropic(max_retries=1, timeout=60.0)
        self._model = model

    def recognize(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> RecognitionResult:
        content: list[dict] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(image).decode("utf-8"),
                    },
                }
            )
        prompt = f"Meal description: {text}" if text else "Identify the food in this photo."
        content.append({"type": "text", "text": prompt})

        data = self._call(RECOGNIZE_SYSTEM, content, RECOGNITION_SCHEMA, effort="medium")
        try:
            status = RecognitionStatus(data["status"])
            dishes = [
                DishGuess(**dish)
                for dish in data.get("dishes", [])
                if isinstance(dish, dict) and float(dish.get("quantity", 0) or 0) > 0
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RecognizerError("AI response did not match the expected format") from exc
        if status is not RecognitionStatus.OK:
            dishes = []
        return RecognitionResult(status=status, dishes=dishes)

    def choose(self, guess: DishGuess, candidates: list[Candidate]) -> str | None:
        codes = [c.code for c in candidates]
        schema = {
            "type": "object",
            "properties": {"code": {"type": "string", "enum": [*codes, "none"]}},
            "required": ["code"],
            "additionalProperties": False,
        }
        lines = "\n".join(f"{c.code}: {c.name}" for c in candidates)
        also = ", ".join(guess.alternative_names) or "none"
        prompt = f"Dish: {guess.name}\nAlso called: {also}\n\nDatabank entries:\n{lines}"
        data = self._call(CHOOSE_SYSTEM, [{"type": "text", "text": prompt}], schema, effort="low")
        code = data.get("code")
        return code if code in codes else None

    def _call(self, system: str, content: list[dict], schema: dict, effort: str) -> dict:
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=system,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIStatusError as exc:
            raise RecognizerError(f"AI service returned an error ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise RecognizerError("Could not reach the AI service") from exc

        if response.stop_reason == "refusal":
            raise RecognizerError("The AI service declined this request")
        if response.stop_reason == "max_tokens":
            raise RecognizerError("The AI response was cut off")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise RecognizerError("The AI response had no text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RecognizerError("The AI response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise RecognizerError("The AI response was not a JSON object")
        return data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_recognizer.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add src/asli/recognizer.py tests/fixtures tests/test_recognizer.py
git commit -m "feat: recognize dishes and choose databank entries with Claude"
```

---

### Task 7: Engine, unmatched log and settings

**Files:**
- Create: `src/asli/unmatched_log.py`, `src/asli/config.py`, `src/asli/engine.py`
- Test: `tests/test_unmatched_log.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6. Fixture `food_db`; fakes `FakeRecognizer`, `FakeChooser`.
- Produces:
  - `asli.unmatched_log.UnmatchedLog(path)` with `record(name: str) -> None` (lower-cased, trimmed, counted) and `most_common(limit: int = 20) -> list[tuple[str, int]]`
  - `asli.config.Settings(food_db_path, unmatched_db_path, household_units_path: Path, model: str, auto_accept_score: float, confirm_below_score: float)` and `load_settings() -> Settings` reading `ASLI_DATA_DIR` (default `data`), `ASLI_FOOD_DB`, `ASLI_UNMATCHED_DB`, `ASLI_HOUSEHOLD_UNITS`, `ASLI_MODEL`, `ASLI_AUTO_ACCEPT_SCORE`, `ASLI_CONFIRM_SCORE`
  - `asli.engine.Engine(recognizer: Recognizer, matcher: Matcher, household: dict[PortionUnit, float], unmatched_log: UnmatchedLog)` with `analyze(image: bytes | None, media_type: str | None, text: str | None) -> AnalysisResult`
  - `asli.engine.build_engine(settings: Settings) -> Engine`

- [ ] **Step 1: Write the failing unmatched-log test**

`tests/test_unmatched_log.py`:

```python
from asli.unmatched_log import UnmatchedLog


def test_counts_names_case_insensitively(tmp_path):
    log = UnmatchedLog(tmp_path / "logs" / "unmatched.sqlite")
    log.record("Thepla")
    log.record(" thepla ")
    log.record("Misal pav")
    log.record("   ")
    assert log.most_common() == [("thepla", 2), ("misal pav", 1)]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_unmatched_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.unmatched_log'`

- [ ] **Step 3: Write the unmatched log and settings**

`src/asli/unmatched_log.py`:

```python
"""Counts dish names that matched nothing in the databank (spec 5.2)."""

import sqlite3
from pathlib import Path


class UnmatchedLog:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._execute(
            "CREATE TABLE IF NOT EXISTS unmatched (name TEXT PRIMARY KEY, count INTEGER NOT NULL)"
        )

    def record(self, name: str) -> None:
        key = name.strip().lower()
        if not key:
            return
        self._execute(
            "INSERT INTO unmatched (name, count) VALUES (?, 1) "
            "ON CONFLICT(name) DO UPDATE SET count = count + 1",
            (key,),
        )

    def most_common(self, limit: int = 20) -> list[tuple[str, int]]:
        rows = self._execute(
            "SELECT name, count FROM unmatched ORDER BY count DESC, name LIMIT ?", (limit,)
        )
        return [(name, count) for name, count in rows]

    def _execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        conn = sqlite3.connect(self._path)
        try:
            with conn:
                return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
```

`src/asli/config.py`:

```python
"""Engine settings from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

from .recognizer import DEFAULT_MODEL


@dataclass(frozen=True)
class Settings:
    food_db_path: Path
    unmatched_db_path: Path
    household_units_path: Path
    model: str
    auto_accept_score: float
    confirm_below_score: float


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("ASLI_DATA_DIR", "data"))
    return Settings(
        food_db_path=Path(os.environ.get("ASLI_FOOD_DB", data_dir / "asli_food.sqlite")),
        unmatched_db_path=Path(os.environ.get("ASLI_UNMATCHED_DB", data_dir / "unmatched.sqlite")),
        household_units_path=Path(
            os.environ.get("ASLI_HOUSEHOLD_UNITS", data_dir / "household_units.csv")
        ),
        model=os.environ.get("ASLI_MODEL", DEFAULT_MODEL),
        auto_accept_score=float(os.environ.get("ASLI_AUTO_ACCEPT_SCORE", "90")),
        confirm_below_score=float(os.environ.get("ASLI_CONFIRM_SCORE", "60")),
    )
```

- [ ] **Step 4: Run the unmatched-log test to verify it passes**

Run: `uv run pytest tests/test_unmatched_log.py -v`
Expected: 1 passed

- [ ] **Step 5: Write the failing engine tests**

`tests/test_engine.py`:

```python
import pytest
from fakes import FakeChooser, FakeRecognizer

from asli.engine import Engine
from asli.interfaces import RecognizerError
from asli.matcher import Matcher
from asli.models import (
    AnalysisStatus,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionResult,
    RecognitionStatus,
)
from asli.unmatched_log import UnmatchedLog

HOUSEHOLD = {PortionUnit.BOWL: 150.0}


def guess(name, unit, quantity, confidence, *alternatives):
    return DishGuess(
        name=name, alternative_names=list(alternatives), unit=unit, quantity=quantity, confidence=confidence
    )


def make_engine(food_db, tmp_path, recognition=None, error=None, matcher=None):
    recognizer = FakeRecognizer(result=recognition, error=error)
    matcher = matcher or Matcher(food_db, FakeChooser(answer=None))
    log = UnmatchedLog(tmp_path / "unmatched.sqlite")
    return Engine(recognizer, matcher, HOUSEHOLD, log), recognizer, log


def ok(*dishes):
    return RecognitionResult(status=RecognitionStatus.OK, dishes=list(dishes))


def test_thali_gives_dishes_and_totals(food_db, tmp_path):
    recognition = ok(
        guess("roti", "piece", 2, "high"),
        guess("rajma", "bowl", 1, "medium"),
        guess("zzzzqqqq", "bowl", 1, "low"),
    )
    engine, _, log = make_engine(food_db, tmp_path, recognition)
    result = engine.analyze(None, None, "2 roti, rajma")

    assert result.status is AnalysisStatus.OK
    roti, rajma, unknown = result.dishes
    assert roti.status == "matched"
    assert roti.match.code == "ASC096"
    assert roti.grams == pytest.approx(72.0)
    assert roti.confidence is Confidence.HIGH
    assert rajma.grams == pytest.approx(150.0)
    assert rajma.confidence is Confidence.MEDIUM
    assert unknown.status == "unmatched"
    assert unknown.nutrients is None
    # 72 g chapati at 8 g/100 g + 150 g rajma at 6 g/100 g; unmatched dish excluded
    assert result.totals.estimate.protein_g == pytest.approx(5.76 + 9.0)
    assert log.most_common() == [("zzzzqqqq", 1)]


def test_ai_choice_lowers_confidence_and_flags_confirmation(food_db, tmp_path):
    matcher = Matcher(food_db, FakeChooser(answer="ASC165"), auto_accept_score=101, confirm_below_score=101)
    engine, _, _ = make_engine(food_db, tmp_path, ok(guess("kidney beans", "bowl", 1, "high")), matcher=matcher)
    dish = engine.analyze(None, None, "kidney beans").dishes[0]
    assert dish.status == "needs_confirmation"
    assert dish.confidence is Confidence.MEDIUM
    assert dish.candidates[0].code == "ASC165"
    assert dish.nutrients is not None


def test_portion_fallback_lowers_confidence(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, ok(guess("curd dip", "serving", 1, "high")))
    dish = engine.analyze(None, None, "curd dip").dishes[0]
    assert dish.grams == pytest.approx(100.0)
    assert dish.confidence is Confidence.MEDIUM


@pytest.mark.parametrize(
    "recognition_status, expected",
    [
        (RecognitionStatus.NO_FOOD, AnalysisStatus.NO_FOOD),
        (RecognitionStatus.UNCLEAR_IMAGE, AnalysisStatus.UNCLEAR_IMAGE),
    ],
)
def test_no_food_and_unclear_image(food_db, tmp_path, recognition_status, expected):
    engine, _, _ = make_engine(food_db, tmp_path, RecognitionResult(status=recognition_status))
    result = engine.analyze(b"img", "image/jpeg", None)
    assert result.status is expected
    assert result.dishes == []
    assert result.totals is None


def test_ok_with_no_dishes_is_no_food(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, ok())
    assert engine.analyze(None, None, "nothing").status is AnalysisStatus.NO_FOOD


def test_recognizer_error_becomes_error_status(food_db, tmp_path):
    engine, _, _ = make_engine(food_db, tmp_path, error=RecognizerError("Could not reach the AI service"))
    result = engine.analyze(None, None, "dal")
    assert result.status is AnalysisStatus.ERROR
    assert result.message == "Could not reach the AI service"


def test_image_is_never_written_to_disk(food_db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine, recognizer, _ = make_engine(food_db, tmp_path, ok(guess("roti", "piece", 1, "high")))
    engine.analyze(b"\xff\xd8 secret photo bytes", "image/jpeg", None)
    assert recognizer.calls[0][0] == b"\xff\xd8 secret photo bytes"
    files = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    assert files <= {"INDB.xlsx", "aliases.csv", "food.sqlite", "unmatched.sqlite"}
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.engine'`

- [ ] **Step 7: Write the engine**

`src/asli/engine.py`:

```python
"""Orchestrates recognition, matching, portions and nutrients for one meal."""

from .calculator import dish_nutrition, total
from .config import Settings
from .food_db import FoodDB
from .interfaces import Recognizer, RecognizerError
from .matcher import Matcher
from .models import (
    AnalysisResult,
    AnalysisStatus,
    AnalyzedDish,
    Candidate,
    Confidence,
    DishGuess,
    PortionUnit,
    RecognitionStatus,
)
from .portions import load_household_units, to_grams
from .unmatched_log import UnmatchedLog


class Engine:
    def __init__(
        self,
        recognizer: Recognizer,
        matcher: Matcher,
        household: dict[PortionUnit, float],
        unmatched_log: UnmatchedLog,
    ):
        self._recognizer = recognizer
        self._matcher = matcher
        self._household = household
        self._unmatched = unmatched_log

    def analyze(
        self, image: bytes | None, media_type: str | None, text: str | None
    ) -> AnalysisResult:
        try:
            recognition = self._recognizer.recognize(image, media_type, text)
            if recognition.status is RecognitionStatus.UNCLEAR_IMAGE:
                return AnalysisResult(status=AnalysisStatus.UNCLEAR_IMAGE)
            if recognition.status is RecognitionStatus.NO_FOOD or not recognition.dishes:
                return AnalysisResult(status=AnalysisStatus.NO_FOOD)
            dishes = [self._analyze_dish(guess) for guess in recognition.dishes]
        except RecognizerError as exc:
            return AnalysisResult(status=AnalysisStatus.ERROR, message=str(exc))

        counted = [dish.nutrients for dish in dishes if dish.nutrients is not None]
        return AnalysisResult(status=AnalysisStatus.OK, dishes=dishes, totals=total(counted))

    def _analyze_dish(self, guess: DishGuess) -> AnalyzedDish:
        match = self._matcher.match(guess)
        if match.entry is None:
            self._unmatched.record(guess.name)
            return AnalyzedDish(
                name=guess.name,
                status="unmatched",
                candidates=match.candidates,
                unit=guess.unit,
                quantity=guess.quantity,
                confidence=Confidence.LOW,
            )

        confidence = guess.confidence
        if match.used_chooser:
            confidence = confidence.lowered()
        portion = to_grams(guess.unit, guess.quantity, match.entry, self._household)
        if portion.reduced_confidence:
            confidence = confidence.lowered()
        nutrition = dish_nutrition(match.entry, portion.grams, confidence)
        return AnalyzedDish(
            name=guess.name,
            status=match.status,
            match=Candidate(code=match.entry.code, name=match.entry.name),
            candidates=match.candidates,
            unit=guess.unit,
            quantity=guess.quantity,
            grams=portion.grams,
            grams_low=nutrition.grams_low,
            grams_high=nutrition.grams_high,
            confidence=confidence,
            nutrients=nutrition.nutrients,
        )


def build_engine(settings: Settings) -> Engine:
    from .recognizer import ClaudeRecognizer

    db = FoodDB(settings.food_db_path)
    recognizer = ClaudeRecognizer(model=settings.model)
    matcher = Matcher(
        db,
        recognizer,
        auto_accept_score=settings.auto_accept_score,
        confirm_below_score=settings.confirm_below_score,
    )
    return Engine(
        recognizer,
        matcher,
        load_household_units(settings.household_units_path),
        UnmatchedLog(settings.unmatched_db_path),
    )
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add src/asli/unmatched_log.py src/asli/config.py src/asli/engine.py tests/test_unmatched_log.py tests/test_engine.py
git commit -m "feat: analyze a meal end to end with the engine"
```

---

### Task 8: Web API

**Files:**
- Create: `src/asli/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `Engine.analyze`, `build_engine` (Task 7); `load_settings` (Task 7); `AnalysisResult`, `AnalysisStatus` (Task 1).
- Produces:
  - `asli.api.create_app(engine: Engine | None = None) -> FastAPI` (builds the real engine lazily on first request when `engine` is `None`)
  - `asli.api.app` (module-level app for `uvicorn asli.api:app`)
  - `GET /health` → `{"status": "ok"}`
  - `POST /analyze` multipart with optional `image` file and optional `text` field → `AnalysisResult` JSON; HTTP 200 for `ok`, `no_food`, `unclear_image`; 503 for `error`; 400 when neither image nor non-empty text, or the image is empty; 415 for an image type other than JPEG, PNG, WebP, GIF; 413 for an image over 5 MB.

- [ ] **Step 1: Write the failing tests**

`tests/test_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from asli.api import MAX_IMAGE_BYTES, create_app
from asli.models import AnalysisResult, AnalysisStatus


class FakeEngine:
    def __init__(self, result: AnalysisResult):
        self.result = result
        self.calls = []

    def analyze(self, image, media_type, text):
        self.calls.append((image, media_type, text))
        return self.result


def client_with(status=AnalysisStatus.OK, message=None):
    engine = FakeEngine(AnalysisResult(status=status, message=message))
    return TestClient(create_app(engine)), engine


def test_health():
    client, _ = client_with()
    assert client.get("/health").json() == {"status": "ok"}


def test_neither_image_nor_text_is_400():
    client, engine = client_with()
    assert client.post("/analyze").status_code == 400
    assert client.post("/analyze", data={"text": "   "}).status_code == 400
    assert engine.calls == []


def test_text_only():
    client, engine = client_with()
    response = client.post("/analyze", data={"text": "2 rotis and dal"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert engine.calls == [(None, None, "2 rotis and dal")]


def test_image_upload_passes_bytes_and_type():
    client, engine = client_with()
    response = client.post("/analyze", files={"image": ("meal.jpg", b"jpeg-bytes", "image/jpeg")})
    assert response.status_code == 200
    assert engine.calls == [(b"jpeg-bytes", "image/jpeg", None)]


def test_unsupported_image_type_is_415():
    client, _ = client_with()
    response = client.post("/analyze", files={"image": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_empty_image_is_400():
    client, _ = client_with()
    response = client.post("/analyze", files={"image": ("meal.jpg", b"", "image/jpeg")})
    assert response.status_code == 400


def test_image_too_large_is_413():
    client, _ = client_with()
    big = b"x" * (MAX_IMAGE_BYTES + 1)
    response = client.post("/analyze", files={"image": ("meal.jpg", big, "image/jpeg")})
    assert response.status_code == 413


@pytest.mark.parametrize("status", [AnalysisStatus.NO_FOOD, AnalysisStatus.UNCLEAR_IMAGE])
def test_no_food_and_unclear_photo_are_200(status):
    client, _ = client_with(status=status)
    response = client.post("/analyze", files={"image": ("meal.jpg", b"jpeg-bytes", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["status"] == status.value


def test_engine_error_is_503_with_message():
    client, _ = client_with(status=AnalysisStatus.ERROR, message="Could not reach the AI service")
    response = client.post("/analyze", data={"text": "dal"})
    assert response.status_code == 503
    assert response.json() == {
        "status": "error", "message": "Could not reach the AI service", "dishes": [], "totals": None,
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.api'`

- [ ] **Step 3: Write the implementation**

`src/asli/api.py`:

```python
"""HTTP API for the Asli engine."""

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import load_settings
from .engine import Engine, build_engine
from .models import AnalysisStatus

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(title="Asli food analysis engine")
    state: dict[str, Engine | None] = {"engine": engine}

    def get_engine() -> Engine:
        if state["engine"] is None:
            state["engine"] = build_engine(load_settings())
        return state["engine"]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/analyze")
    async def analyze(
        image: UploadFile | None = File(None),
        text: str | None = Form(None),
    ) -> JSONResponse:
        text = text.strip() if text else None
        if image is None and not text:
            raise HTTPException(status_code=400, detail="Send a photo, a text description, or both.")

        data: bytes | None = None
        media_type: str | None = None
        if image is not None:
            media_type = image.content_type
            if media_type not in ALLOWED_IMAGE_TYPES:
                raise HTTPException(status_code=415, detail="Photo must be JPEG, PNG, WebP or GIF.")
            data = await image.read()
            if not data:
                raise HTTPException(status_code=400, detail="The photo is empty.")
            if len(data) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")

        result = await run_in_threadpool(get_engine().analyze, data, media_type, text)
        status_code = 503 if result.status is AnalysisStatus.ERROR else 200
        return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))

    return app


app = create_app()
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/asli/api.py tests/test_api.py
git commit -m "feat: expose the engine as a web API"
```

---

### Task 9: Accuracy evaluation

**Files:**
- Create: `src/asli/evaluate.py`, `eval/meals.example.jsonl`
- Test: `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `FoodDB.get` (Task 2); `AnalysisResult`, `AnalyzedDish`, `Candidate`, `Nutrients`, `NutrientRange` (Task 1); `build_engine`, `load_settings` (Task 7).
- Produces:
  - `asli.evaluate.TruthDish(code: str, grams: float)`, `TruthMeal(id: str, image: str | None, text: str | None, dishes: list[TruthDish])` (Pydantic)
  - `asli.evaluate.MealScore(meal_id, dishes_found, dishes_total, portion_errors: list[float], protein_error_g: float)` (dataclass)
  - `asli.evaluate.Summary(meals, identification_accuracy, mean_portion_error, mean_protein_error_g)` (dataclass)
  - `asli.evaluate.load_meals(path: Path) -> list[TruthMeal]`
  - `asli.evaluate.score_meal(prediction: AnalysisResult, truth: TruthMeal, db: FoodDB) -> MealScore`
  - `asli.evaluate.summarize(scores: list[MealScore]) -> Summary`
  - CLI: `python -m asli.evaluate eval/meals.jsonl` (calls the real API, costs money)

Metrics (spec section 7): identification accuracy = truth dishes whose code appears among predicted matches ÷ all truth dishes; portion error = |predicted grams − true grams| ÷ true grams for each found dish; protein error = |predicted total protein − true total protein| per meal, with true protein computed from the databank.

- [ ] **Step 1: Create the evaluation set format example**

`eval/meals.example.jsonl` (one meal per line; `image` is relative to the file; copy to `eval/meals.jsonl` and add real weighed meals):

```json
{"id": "lunch-001", "image": "photos/lunch-001.jpg", "text": null, "dishes": [{"code": "ASC096", "grams": 72}, {"code": "ASC165", "grams": 180}]}
{"id": "dinner-001", "image": null, "text": "3 idli and a bowl of sambar", "dishes": [{"code": "ASC144", "grams": 75}, {"code": "ASC167", "grams": 160}]}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_evaluate.py`:

```python
import pytest

from asli.evaluate import MealScore, TruthDish, TruthMeal, load_meals, score_meal, summarize
from asli.models import (
    AnalysisResult,
    AnalysisStatus,
    AnalyzedDish,
    Candidate,
    Nutrients,
    NutrientRange,
)


def predicted(code, grams):
    return AnalyzedDish(
        name=code, status="matched", match=Candidate(code=code, name=code),
        unit="bowl", quantity=1, grams=grams, confidence="high",
    )


def prediction(dishes, protein):
    n = Nutrients(protein_g=protein)
    return AnalysisResult(
        status=AnalysisStatus.OK, dishes=dishes, totals=NutrientRange(estimate=n, low=n, high=n)
    )


def test_score_meal(food_db):
    truth = TruthMeal(id="m1", dishes=[TruthDish(code="ASC096", grams=72), TruthDish(code="ASC165", grams=200)])
    # truth protein: 72 g * 8/100 + 200 g * 6/100 = 5.76 + 12 = 17.76
    pred = prediction([predicted("ASC096", 36)], protein=2.88)
    score = score_meal(pred, truth, food_db)
    assert score.dishes_found == 1
    assert score.dishes_total == 2
    assert score.portion_errors == [pytest.approx(0.5)]
    assert score.protein_error_g == pytest.approx(17.76 - 2.88)


def test_score_meal_with_no_prediction(food_db):
    truth = TruthMeal(id="m2", dishes=[TruthDish(code="ASC096", grams=36)])
    score = score_meal(AnalysisResult(status=AnalysisStatus.ERROR), truth, food_db)
    assert score.dishes_found == 0
    assert score.protein_error_g == pytest.approx(2.88)


def test_summarize():
    scores = [
        MealScore("a", 1, 2, [0.5], 4.0),
        MealScore("b", 2, 2, [0.1, 0.3], 2.0),
    ]
    summary = summarize(scores)
    assert summary.meals == 2
    assert summary.identification_accuracy == pytest.approx(3 / 4)
    assert summary.mean_portion_error == pytest.approx(0.3)
    assert summary.mean_protein_error_g == pytest.approx(3.0)


def test_load_meals(tmp_path):
    path = tmp_path / "meals.jsonl"
    path.write_text(
        '{"id": "x", "image": null, "text": "dal", "dishes": [{"code": "ASC165", "grams": 150}]}\n\n',
        encoding="utf-8",
    )
    meals = load_meals(path)
    assert [m.id for m in meals] == ["x"]
    assert meals[0].dishes[0].grams == 150
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'asli.evaluate'`

- [ ] **Step 4: Write the implementation**

`src/asli/evaluate.py`:

```python
"""Score the engine against weighed meals (spec section 7)."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from .food_db import FoodDB
from .models import AnalysisResult

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class TruthDish(BaseModel):
    code: str
    grams: float


class TruthMeal(BaseModel):
    id: str
    image: str | None = None
    text: str | None = None
    dishes: list[TruthDish]


@dataclass
class MealScore:
    meal_id: str
    dishes_found: int
    dishes_total: int
    portion_errors: list[float]
    protein_error_g: float


@dataclass
class Summary:
    meals: int
    identification_accuracy: float
    mean_portion_error: float
    mean_protein_error_g: float


def load_meals(path: Path) -> list[TruthMeal]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [TruthMeal.model_validate_json(line) for line in lines if line.strip()]


def score_meal(prediction: AnalysisResult, truth: TruthMeal, db: FoodDB) -> MealScore:
    predicted_grams: dict[str, float] = defaultdict(float)
    for dish in prediction.dishes:
        if dish.match is not None and dish.grams is not None:
            predicted_grams[dish.match.code] += dish.grams

    found = 0
    portion_errors: list[float] = []
    true_protein = 0.0
    for dish in truth.dishes:
        entry = db.get(dish.code)
        if entry is None:
            raise ValueError(f"Meal {truth.id}: unknown food code {dish.code}")
        true_protein += entry.protein_g * dish.grams / 100.0
        if dish.code in predicted_grams:
            found += 1
            portion_errors.append(abs(predicted_grams[dish.code] - dish.grams) / dish.grams)

    predicted_protein = prediction.totals.estimate.protein_g if prediction.totals else 0.0
    return MealScore(
        meal_id=truth.id,
        dishes_found=found,
        dishes_total=len(truth.dishes),
        portion_errors=portion_errors,
        protein_error_g=abs(predicted_protein - true_protein),
    )


def summarize(scores: list[MealScore]) -> Summary:
    total_dishes = sum(s.dishes_total for s in scores)
    errors = [e for s in scores for e in s.portion_errors]
    return Summary(
        meals=len(scores),
        identification_accuracy=sum(s.dishes_found for s in scores) / total_dishes if total_dishes else 0.0,
        mean_portion_error=sum(errors) / len(errors) if errors else 0.0,
        mean_protein_error_g=sum(s.protein_error_g for s in scores) / len(scores) if scores else 0.0,
    )


def main(argv: list[str] | None = None) -> None:
    from .config import load_settings
    from .engine import build_engine

    parser = argparse.ArgumentParser(description="Score the engine on weighed meals (calls the real AI API).")
    parser.add_argument("meals", type=Path)
    args = parser.parse_args(argv)

    settings = load_settings()
    engine = build_engine(settings)
    db = FoodDB(settings.food_db_path)
    scores = []
    for meal in load_meals(args.meals):
        image = media_type = None
        if meal.image:
            image_path = args.meals.parent / meal.image
            image = image_path.read_bytes()
            media_type = MEDIA_TYPES[image_path.suffix.lower()]
        result = engine.analyze(image, media_type, meal.text)
        score = score_meal(result, meal, db)
        scores.append(score)
        print(
            f"{meal.id}: status={result.status.value} found={score.dishes_found}/{score.dishes_total} "
            f"protein_error={score.protein_error_g:.1f} g"
        )

    summary = summarize(scores)
    print(
        f"\n{summary.meals} meals | dish identification {summary.identification_accuracy:.0%} | "
        f"mean portion error {summary.mean_portion_error:.0%} | "
        f"mean protein error {summary.mean_protein_error_g:.1f} g"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run them to verify they pass**

Run: `uv run pytest tests/test_evaluate.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/asli/evaluate.py eval/meals.example.jsonl tests/test_evaluate.py
git commit -m "feat: score the engine against weighed meals"
```

---

### Task 10: Real data, live tests and README

**Files:**
- Create: `scripts/download_indb.sh`, `data/aliases.csv`, `tests/live/test_live_claude.py`, `README.md`

**Interfaces:**
- Consumes: `asli.importer` CLI (Task 2), `ClaudeRecognizer` (Task 6), `asli.api:app` (Task 8).
- Produces: a working local database at `data/asli_food.sqlite` (not committed) and run instructions.

- [ ] **Step 1: Write the download script and starter aliases**

`scripts/download_indb.sh`:

```bash
#!/usr/bin/env bash
# Downloads the Indian Nutrient Databank spreadsheet into data/raw/ (not committed:
# the repository has no licence file, so commercial use needs the authors' permission).
set -euo pipefail
mkdir -p data/raw
curl -fsSL -o data/raw/INDB.xlsx \
  https://raw.githubusercontent.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-/main/INDB.xlsx
echo "Saved data/raw/INDB.xlsx"
```

`data/aliases.csv` (codes checked against INDB.xlsx on 2026-11-17):

```csv
alias,food_code
roti,ASC096
phulka,ASC096
chapati,ASC096
rice,ASC113
chawal,ASC113
plain rice,ASC113
rajma,ASC165
rajma curry,ASC165
sambar,ASC167
idli,ASC144
dosa,BFP148
plain dosa,BFP148
masala dosa,ASC146
poha,BFP044
palak paneer,ASC215
matar paneer,ASC191
paneer butter masala,ASC222
shahi paneer,ASC221
kadai paneer,ASC226
bhindi,BFP269
bhindi sabzi,BFP269
```

- [ ] **Step 2: Download and import the real databank**

Run:

```bash
chmod +x scripts/download_indb.sh && ./scripts/download_indb.sh
uv run python -m asli.importer data/raw/INDB.xlsx --aliases data/aliases.csv --out data/asli_food.sqlite
```

Expected: `Imported 1014 foods into data/asli_food.sqlite` (the count comes from the file; any value above 1000 is fine). If it raises `ValueError` for an alias, the code in `data/aliases.csv` is wrong: fix that row.

- [ ] **Step 3: Write the live tests**

`tests/live/test_live_claude.py`:

```python
"""Calls the real Claude API. Costs money. Run with: ASLI_LIVE=1 uv run pytest -m live -v"""

import os

import pytest

from asli.models import Candidate, DishGuess, RecognitionStatus
from asli.recognizer import ClaudeRecognizer

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("ASLI_LIVE") != "1", reason="set ASLI_LIVE=1 to call the real API"),
]


def test_text_meal_is_recognized():
    result = ClaudeRecognizer().recognize(None, None, "2 rotis and a bowl of rajma")
    assert result.status is RecognitionStatus.OK
    words = " ".join(
        f"{d.name} {' '.join(d.alternative_names)}".lower() for d in result.dishes
    )
    assert "roti" in words or "chapati" in words
    assert "rajma" in words or "kidney" in words


def test_choose_picks_the_same_dish():
    guess = DishGuess(name="rajma", alternative_names=["kidney bean curry"], unit="bowl", quantity=1, confidence="high")
    candidates = [
        Candidate(code="ASC167", name="Sambar"),
        Candidate(code="ASC165", name="Kidney bean curry (Rajmah curry)"),
    ]
    assert ClaudeRecognizer().choose(guess, candidates) == "ASC165"
```

Run: `uv run pytest -v`
Expected: all unit tests pass; the 2 live tests are reported as skipped.

Run (needs an Anthropic API key or `ant auth login`; costs a few cents): `ASLI_LIVE=1 uv run pytest -m live -v`
Expected: 2 passed. If `test_request_sends_image_schema_and_fallback` passed but the live call fails with a 400 about `fallbacks`, the installed `anthropic` package is too old: run `uv lock --upgrade-package anthropic && uv sync` and retry.

- [ ] **Step 4: Write the README**

`README.md`:

````markdown
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
````

- [ ] **Step 5: Smoke-test the running API**

Run in one terminal: `uv run uvicorn asli.api:app`
Run in another: `curl -s -F "text=2 rotis and a bowl of rajma" http://127.0.0.1:8000/analyze`
Expected: JSON with `"status":"ok"`, a `chapati`/`roti` dish matched to `ASC096` with `grams` 72 (if the model used the unit "piece"), a rajma dish matched to `ASC165` (150 g if the model used "bowl"), and `totals.estimate.protein_g` above 0. Stop the server afterwards.

- [ ] **Step 6: Commit**

```bash
git add scripts/download_indb.sh data/aliases.csv tests/live/test_live_claude.py README.md
git commit -m "feat: real databank import, live tests and README"
```
