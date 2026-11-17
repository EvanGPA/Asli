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
