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
