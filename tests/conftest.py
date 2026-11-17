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
