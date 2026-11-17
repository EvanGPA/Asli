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
