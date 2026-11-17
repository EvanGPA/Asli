"""Build the Asli food database (SQLite) from the Indian Nutrient Databank spreadsheet."""

import argparse
import csv
import os
import re
import sqlite3
import tempfile
from pathlib import Path

import openpyxl

from .models import PortionUnit

# A "piece" heavier than this is a whole recipe or a large portion, not a countable item
# whose INDB weight can be trusted at full confidence (spec 4.4 rule 2), so it is stored
# as a serving and a "piece" request for it falls to rule 4.
MAX_PIECE_GRAMS = 250

_CONTAINER_UNITS = {
    "bowl": PortionUnit.BOWL,
    "small bowl": PortionUnit.BOWL,
    "soup bowl": PortionUnit.BOWL,
    "curry bowl": PortionUnit.BOWL,
    "katori": PortionUnit.BOWL,
    "plate": PortionUnit.PLATE,
    "small plate": PortionUnit.PLATE,
    "dish": PortionUnit.PLATE,
    "shallow dish": PortionUnit.PLATE,
    "casserole dish": PortionUnit.PLATE,
    "small casserole dish": PortionUnit.PLATE,
    "souffle dish": PortionUnit.PLATE,
    "cup": PortionUnit.CUP,
    "tea cup": PortionUnit.CUP,
    "ice cream cup": PortionUnit.CUP,
    "ice-cream cup": PortionUnit.CUP,
    "souffle cup": PortionUnit.CUP,
    "glass": PortionUnit.GLASS,
    "tall glass": PortionUnit.GLASS,
    "juice glass": PortionUnit.GLASS,
    "sundae glass": PortionUnit.GLASS,
    "tall stemmed glass": PortionUnit.GLASS,
    "tablespoon": PortionUnit.TABLESPOON,
    "teaspoon": PortionUnit.TEASPOON,
    "serving": PortionUnit.SERVING,
}

# Genuinely countable serving units, taken from the distinct servings_unit values in
# INDB.xlsx (checked 2026-11-17). Anything not listed here or above (jar, box, ml, gm,
# half-pints, cake, pie, flan, chicken, fish, portion, small mould ...) is a serving.
_COUNTABLE_UNITS = frozenset({
    "piece", "large piece",
    # breads and pancakes
    "chapati", "roti", "naan", "parantha", "poori", "bhatura", "thepla", "khakhra",
    "dosa", "pesarattu", "uttapam", "appam", "cheela", "pancake", "idli", "puttu",
    "dhokla", "muthia", "omelette", "egg",
    # snacks
    "samosa", "kachori", "vada", "bonda", "cutlet", "tikki", "patty", "pakora",
    "mulik/fritter", "kabab", "kebab", "kofta", "gushtaba", "chop", "chops", "fillet",
    "joint", "chicken breast", "kaathi roll", "roll", "spring roll", "bread roll",
    "sandwich", "triangle", "toasted triangle", "ribbon", "square", "finger", "toast",
    "burger", "hot dog bun", "bun", "puff", "horn", "nest", "basket", "aigrette",
    "straw", "potato", "capsicum", "brinjal", "tomato", "stuffed tomato",
    "cauliflower steak",
    # sweets and bakes
    "ladoo", "burfi", "gulab jamun", "malqura", "tukra", "gunjia", "kulfi", "candy",
    "biscuit", "cookie", "cookies", "gingerman", "slice", "large slice", "tart",
    "pastry", "swiss roll", "éclair", "shell", "swan", "meringue", "orange case",
})

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
    """Map an INDB serving unit to our units. Only listed countable units become pieces."""
    if raw is None:
        return PortionUnit.SERVING
    key = " ".join(str(raw).lower().split())
    if key in _CONTAINER_UNITS:
        return _CONTAINER_UNITS[key]
    if key in _COUNTABLE_UNITS:
        return PortionUnit.PIECE
    return PortionUnit.SERVING


def stored_unit(raw: str | None, serving_grams: float | None) -> PortionUnit:
    """The unit stored for an entry: a piece over MAX_PIECE_GRAMS is stored as a serving."""
    unit = canonical_unit(raw)
    if unit is PortionUnit.PIECE and serving_grams is not None and serving_grams > MAX_PIECE_GRAMS:
        return PortionUnit.SERVING
    return unit


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
    """Build the database into a temporary file beside `out`, then atomically replace `out`.

    If anything fails, the existing database at `out` is left untouched.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        count = _build_into(indb_xlsx, aliases_csv, tmp)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return count


def _build_into(indb_xlsx: Path, aliases_csv: Path | None, out: Path) -> int:
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
            serving_grams = _serving_grams(row, col)
            conn.execute(
                "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    name,
                    stored_unit(row[col["servings_unit"]], serving_grams).value,
                    serving_grams,
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
