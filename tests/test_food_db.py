import pytest

from asli.food_db import FoodDB
import openpyxl

from asli.importer import MAX_PIECE_GRAMS, build_db, canonical_unit, name_variants
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
        ("Piece", PortionUnit.PIECE),
        ("dosa", PortionUnit.PIECE),
        ("samosa", PortionUnit.PIECE),
        ("triangle", PortionUnit.PIECE),
        ("kaathi roll", PortionUnit.PIECE),
        ("pesarattu", PortionUnit.PIECE),
        ("juice glass", PortionUnit.GLASS),
        ("sundae glass", PortionUnit.GLASS),
        ("tall stemmed glass", PortionUnit.GLASS),
        ("ice cream cup", PortionUnit.CUP),
        ("ice-cream cup", PortionUnit.CUP),
        ("souffle cup", PortionUnit.CUP),
        ("casserole dish", PortionUnit.PLATE),
        ("souffle dish", PortionUnit.PLATE),
        ("small casserole dish", PortionUnit.PLATE),
        ("jar", PortionUnit.SERVING),
        ("glass jar", PortionUnit.SERVING),
        ("box", PortionUnit.SERVING),
        ("ml", PortionUnit.SERVING),
        ("gm", PortionUnit.SERVING),
        ("half-pints", PortionUnit.SERVING),
        ("chicken", PortionUnit.SERVING),
        ("cake", PortionUnit.SERVING),
        ("pie", PortionUnit.SERVING),
        ("something unheard of", PortionUnit.SERVING),
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


def _write_indb(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "food_code", "food_name", "servings_unit", "energy_kcal", "protein_g", "carb_g",
        "fat_g", "fibre_g", "unit_serving_energy_kcal", "unit_serving_protein_g",
    ])
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_heavy_piece_is_stored_as_serving(tmp_path):
    assert MAX_PIECE_GRAMS == 250
    xlsx = _write_indb(tmp_path / "INDB.xlsx", [
        # 100 kcal/100 g: 250 kcal per piece -> 250 g (at the cap, stays a piece)
        ["P250", "Big cutlet", "cutlet", 100.0, 5.0, 10.0, 5.0, 1.0, 250.0, None],
        # 1441 kcal per piece -> 1,441 g (whole recipe): stored as a serving
        ["P1441", "Tandoori thing", "piece", 100.0, 5.0, 10.0, 5.0, 1.0, 1441.0, None],
        # no serving weight: a countable unit stays a piece
        ["PNONE", "Mystery vada", "vada", 100.0, 5.0, 10.0, 5.0, 1.0, None, None],
    ])
    out = tmp_path / "food.sqlite"
    build_db(xlsx, None, out)
    db = FoodDB(out)
    assert db.get("P250").serving_unit is PortionUnit.PIECE
    assert db.get("P1441").serving_unit is PortionUnit.SERVING
    assert db.get("P1441").serving_grams == pytest.approx(1441.0)
    assert db.get("PNONE").serving_unit is PortionUnit.PIECE


def test_failed_build_keeps_existing_database(tmp_path, indb_xlsx):
    out = tmp_path / "food.sqlite"
    build_db(indb_xlsx, None, out)
    before = out.read_bytes()
    bad = tmp_path / "bad.csv"
    bad.write_text("alias,food_code\nchole,NOPE\n", encoding="utf-8")
    with pytest.raises(ValueError, match="NOPE"):
        build_db(indb_xlsx, bad, out)
    assert out.read_bytes() == before
    assert FoodDB(out).get("ASC096").name == "Chapati/Roti"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["INDB.xlsx", "bad.csv", "food.sqlite"]


def test_missing_database_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="asli.importer"):
        FoodDB(tmp_path / "missing.sqlite")
