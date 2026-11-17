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
