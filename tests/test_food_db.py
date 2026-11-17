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
