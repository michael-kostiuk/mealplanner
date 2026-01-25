import re
import unicodedata
from enum import Enum


class BaseUnit(str, Enum):
    G = "g"
    KG = "kg"
    ML = "ml"
    L = "l"
    CUP = "cup"
    TBSP = "tbsp"
    TSP = "tsp"
    PIECE = "piece"
    SLICE = "slice"
    CLOVE = "clove"
    BUNCH = "bunch"
    CAN = "can"
    PACKAGE = "package"


_UNIT_ALIASES = {
    # Mass
    "g": BaseUnit.G.value,
    "gram": BaseUnit.G.value,
    "grams": BaseUnit.G.value,
    "gr": BaseUnit.G.value,
    "gm": BaseUnit.G.value,
    "gms": BaseUnit.G.value,
    "г": BaseUnit.G.value,
    "гр": BaseUnit.G.value,
    "грам": BaseUnit.G.value,
    "грамм": BaseUnit.G.value,
    "грамів": BaseUnit.G.value,
    "граммов": BaseUnit.G.value,
    "кг": BaseUnit.KG.value,
    "kg": BaseUnit.KG.value,
    "kilo": BaseUnit.KG.value,
    "kilogram": BaseUnit.KG.value,
    "kilograms": BaseUnit.KG.value,
    "кілограм": BaseUnit.KG.value,
    "кілограмів": BaseUnit.KG.value,
    "килограмм": BaseUnit.KG.value,
    "килограммов": BaseUnit.KG.value,
    # Volume
    "ml": BaseUnit.ML.value,
    "milliliter": BaseUnit.ML.value,
    "milliliters": BaseUnit.ML.value,
    "millilitre": BaseUnit.ML.value,
    "millilitres": BaseUnit.ML.value,
    "мл": BaseUnit.ML.value,
    "l": BaseUnit.L.value,
    "liter": BaseUnit.L.value,
    "liters": BaseUnit.L.value,
    "litre": BaseUnit.L.value,
    "litres": BaseUnit.L.value,
    "л": BaseUnit.L.value,
    "літр": BaseUnit.L.value,
    "літра": BaseUnit.L.value,
    "литр": BaseUnit.L.value,
    "литра": BaseUnit.L.value,
    # Spoon/cup
    "tbsp": BaseUnit.TBSP.value,
    "tablespoon": BaseUnit.TBSP.value,
    "tablespoons": BaseUnit.TBSP.value,
    "tbs": BaseUnit.TBSP.value,
    "tbl": BaseUnit.TBSP.value,
    "tbls": BaseUnit.TBSP.value,
    "stl": BaseUnit.TBSP.value,
    "стл": BaseUnit.TBSP.value,
    "столоваложка": BaseUnit.TBSP.value,
    "cda": BaseUnit.TBSP.value,
    "cucharada": BaseUnit.TBSP.value,
    "cucharadas": BaseUnit.TBSP.value,
    "tsp": BaseUnit.TSP.value,
    "teaspoon": BaseUnit.TSP.value,
    "teaspoons": BaseUnit.TSP.value,
    "tspn": BaseUnit.TSP.value,
    "chl": BaseUnit.TSP.value,
    "чл": BaseUnit.TSP.value,
    "чайналожка": BaseUnit.TSP.value,
    "cdta": BaseUnit.TSP.value,
    "cucharadita": BaseUnit.TSP.value,
    "cucharaditas": BaseUnit.TSP.value,
    "cup": BaseUnit.CUP.value,
    "cups": BaseUnit.CUP.value,
    "стакан": BaseUnit.CUP.value,
    "стакани": BaseUnit.CUP.value,
    "стакана": BaseUnit.CUP.value,
    "склянка": BaseUnit.CUP.value,
    "склянки": BaseUnit.CUP.value,
    "склянок": BaseUnit.CUP.value,
    "taza": BaseUnit.CUP.value,
    "tazas": BaseUnit.CUP.value,
    # Count
    "piece": BaseUnit.PIECE.value,
    "pieces": BaseUnit.PIECE.value,
    "pc": BaseUnit.PIECE.value,
    "pcs": BaseUnit.PIECE.value,
    "unit": BaseUnit.PIECE.value,
    "units": BaseUnit.PIECE.value,
    "шт": BaseUnit.PIECE.value,
    "штук": BaseUnit.PIECE.value,
    "штука": BaseUnit.PIECE.value,
    "штуки": BaseUnit.PIECE.value,
    "pieza": BaseUnit.PIECE.value,
    "piezas": BaseUnit.PIECE.value,
    "slice": BaseUnit.SLICE.value,
    "slices": BaseUnit.SLICE.value,
    "ломтик": BaseUnit.SLICE.value,
    "ломтики": BaseUnit.SLICE.value,
    "скибка": BaseUnit.SLICE.value,
    "скибки": BaseUnit.SLICE.value,
    "rebanada": BaseUnit.SLICE.value,
    "rebanadas": BaseUnit.SLICE.value,
    "clove": BaseUnit.CLOVE.value,
    "cloves": BaseUnit.CLOVE.value,
    "зубчик": BaseUnit.CLOVE.value,
    "зубчики": BaseUnit.CLOVE.value,
    "diente": BaseUnit.CLOVE.value,
    "dientes": BaseUnit.CLOVE.value,
    "bunch": BaseUnit.BUNCH.value,
    "bunches": BaseUnit.BUNCH.value,
    "пучок": BaseUnit.BUNCH.value,
    "пучки": BaseUnit.BUNCH.value,
    "ramo": BaseUnit.BUNCH.value,
    "ramos": BaseUnit.BUNCH.value,
    "manojo": BaseUnit.BUNCH.value,
    "manojos": BaseUnit.BUNCH.value,
    "can": BaseUnit.CAN.value,
    "cans": BaseUnit.CAN.value,
    "банка": BaseUnit.CAN.value,
    "банки": BaseUnit.CAN.value,
    "lata": BaseUnit.CAN.value,
    "latas": BaseUnit.CAN.value,
    "package": BaseUnit.PACKAGE.value,
    "packages": BaseUnit.PACKAGE.value,
    "pack": BaseUnit.PACKAGE.value,
    "packs": BaseUnit.PACKAGE.value,
    "pkg": BaseUnit.PACKAGE.value,
    "pkgs": BaseUnit.PACKAGE.value,
    "пачка": BaseUnit.PACKAGE.value,
    "пачки": BaseUnit.PACKAGE.value,
    "упаковка": BaseUnit.PACKAGE.value,
    "упаковки": BaseUnit.PACKAGE.value,
    "paquete": BaseUnit.PACKAGE.value,
    "paquetes": BaseUnit.PACKAGE.value,
}

_PUNCT_RE = re.compile(r"[^\w\s]+", flags=re.UNICODE)


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_unit_token(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("’", "'").replace("`", "'").replace("'", "")
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def normalize_unit(value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, BaseUnit):
        return value.value
    raw = str(value).strip()
    if not raw:
        return None
    normalized = _normalize_unit_token(raw)
    if not normalized:
        return None
    folded = _fold_text(normalized)
    candidates = [
        normalized,
        normalized.replace(" ", ""),
        folded,
        folded.replace(" ", ""),
    ]
    for candidate in candidates:
        mapped = _UNIT_ALIASES.get(candidate)
        if mapped:
            return mapped
    return None
