"""
Offline lookup against a bundled FoodData Central SQLite snapshot.
"""

import json
import logging
import os
import re
import sqlite3
import threading
import unicodedata

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.getenv(
    "FDC_SQLITE_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "fdc.sqlite")),
)
DEFAULT_SYNONYMS_PATH = os.getenv(
    "FDC_SYNONYMS_PATH",
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "fdc_synonyms.json")
    ),
)

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()
_synonyms: dict[str, str] = {}

PROCESSED_BLOCKLIST = {
    "pie",
    "juice",
    "babyfood",
    "yogurt",
    "dessert",
    "cereal",
    "pudding",
    "roll",
    "candies",
    "candy",
    "syrup",
}


class FdcLookupError(Exception):
    """Raised when lookup cannot be performed (e.g., DB missing)."""


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^0-9a-z\u0400-\u04FF]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _load_synonyms() -> dict[str, str]:
    # This should be replaced to proper translation in future updates
    path = DEFAULT_SYNONYMS_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load FDC synonyms: %s", exc)
        return {}
    normalized = {}
    for key, value in data.items():
        normalized[_normalize(key)] = value
    return normalized


def _get_conn() -> sqlite3.Connection:
    global _conn, _synonyms
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is None:
            if not os.path.exists(DEFAULT_DB_PATH):
                raise FdcLookupError(f"FDC SQLite not found at {DEFAULT_DB_PATH}")
            _conn = sqlite3.connect(DEFAULT_DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _synonyms = _load_synonyms()
    return _conn


def _best_portion(portions: list[dict]) -> float | None:
    """Pick a representative gram weight for converting non-gram base units."""
    for p in portions:
        gram_weight = p.get("gram_weight")
        if gram_weight and gram_weight > 0:
            return gram_weight
    return None


def _score_candidate(description: str, tokens: list[str]) -> float | None:
    """
    Score based on full token containment, data_type preference, and penalties.
    Returns None if token containment fails or blocklist hits.
    """
    normalized_desc = _normalize(description)
    desc_tokens = normalized_desc.split()

    # Block obvious processed items unless explicitly asked (tokens contain the processed term)
    if any(b in desc_tokens for b in PROCESSED_BLOCKLIST) and not any(
        b in tokens for b in PROCESSED_BLOCKLIST
    ):
        return None

    def _contains(token: str) -> bool:
        for dt in desc_tokens:
            if dt == token:
                return True
            if dt.rstrip("s") == token or token.rstrip("s") == dt:
                return True
            if dt.endswith("es") and dt[:-2] == token:
                return True
            if token.endswith("es") and token[:-2] == dt:
                return True
        return False

    if not all(_contains(t) for t in tokens):
        return None

    match_count = len(tokens)
    extra_tokens = max(len(desc_tokens) - match_count, 0)
    score = match_count * 10 - extra_tokens * 0.2

    if "raw" in desc_tokens or "skin" in desc_tokens:
        score += 3

    return score


def _data_type_weight(row: sqlite3.Row) -> int:
    dt = (row["data_type"] or "").lower()
    if dt.startswith("foundation"):
        return 6
    if "sr_legacy" in dt:
        return 3
    return 0


def _search(name: str, base_unit: str | None, allow_ascii: bool = False) -> list[sqlite3.Row]:
    conn = _get_conn()
    global _synonyms
    if not _synonyms:
        _synonyms = _load_synonyms()
    normalized = _normalize(name)
    synonyms_hit = _synonyms.get(normalized, normalized)
    if synonyms_hit == normalized and normalized.isascii() and not allow_ascii:
        return []
    tokens = [t for t in _normalize(synonyms_hit).split() if t]
    scoring_tokens = list(tokens)
    if (
        base_unit
        and base_unit.lower() in ("g", "gram", "grams", "unit", "piece")
        and len(tokens) == 1
        and "raw" not in scoring_tokens
    ):
        scoring_tokens.append("raw")

    if not tokens:
        return []
    query = " ".join(f"{t}*" for t in tokens)
    cursor = conn.execute(
        """
        SELECT f.fdc_id, f.description, f.calories, f.protein, f.carbs, f.fats, f.portions_json, f.data_type
        FROM foods f
        JOIN foods_fts fts ON f.rowid = fts.rowid
        WHERE fts.search_name MATCH ?
        LIMIT 15
        """,
        (query,),
    )
    rows = cursor.fetchall()

    if not rows:
        like_clauses = " AND ".join("search_name LIKE ?" for _ in tokens)
        params = [f"%{t}%" for t in tokens]
        cursor = conn.execute(
            f"""
            SELECT fdc_id, description, calories, protein, carbs, fats, portions_json, data_type
            FROM foods
            WHERE {like_clauses}
            LIMIT 15
            """,
            params,
        )
        rows = cursor.fetchall()
    scored = []
    for r in rows:
        score = _score_candidate(r["description"], scoring_tokens)
        if score is None:
            continue
        score += _data_type_weight(r)
        scored.append((score, r))

    # If raw hint filtered everything out, retry without it.
    if not scored and "raw" in scoring_tokens:
        scoring_tokens_no_raw = [t for t in scoring_tokens if t != "raw"]
        for r in rows:
            score = _score_candidate(r["description"], scoring_tokens_no_raw)
            if score is None:
                continue
            score += _data_type_weight(r)
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored]


def lookup_nutrition(
    ingredient_name: str,
    base_unit: str | None,
    allow_ascii: bool = False,
) -> dict[str, float] | None:
    """
    Find macros per base_unit for the given ingredient name.
    Returns None if no confident match is found.
    """
    candidates = _search(ingredient_name, base_unit, allow_ascii=allow_ascii)
    if not candidates:
        return None
    picked = candidates[0]
    try:
        portions = json.loads(picked["portions_json"]) if picked["portions_json"] else []
    except json.JSONDecodeError:
        portions = []

    calories = float(picked["calories"])
    protein = float(picked["protein"])
    carbs = float(picked["carbs"])
    fats = float(picked["fats"])

    if not base_unit:
        base_unit = "g"
    normalized_unit = base_unit.lower()

    # Macro values in the snapshot are per 100 grams.
    if normalized_unit in ("g", "gram", "grams"):
        return {"calories": calories, "protein": protein, "carbs": carbs, "fats": fats}

    weight = _best_portion(portions)
    if normalized_unit in ("ml", "milliliter", "millilitre", "l", "liter", "litre"):
        # Assume 1 g ~ 1 ml as a fallback density.
        weight = 100.0 if weight is None else weight

    if weight:
        factor = weight / 100.0
        return {
            "calories": calories * factor,
            "protein": protein * factor,
            "carbs": carbs * factor,
            "fats": fats * factor,
        }

    # No portion weight to convert; fall back to per-100g numbers.
    return {"calories": calories, "protein": protein, "carbs": carbs, "fats": fats}
