"""
Offline lookup against a bundled FoodData Central SQLite snapshot.

Public API:
- lookup_nutrition: Find macros for an ingredient
- get_fdc_connection: Get SQLite connection for FDC database
- normalize_text: Normalize text for FDC search
- score_fdc_candidate: Score a candidate match
- get_data_type_weight: Get weight bonus for data_type
- load_synonyms: Load synonym dictionary
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


def normalize_text(text: str) -> str:
    """Normalize text for FDC search - lowercase, remove accents, keep alphanumeric and Cyrillic."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^0-9a-z\u0400-\u04FF]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Alias for backward compatibility
_normalize = normalize_text


def load_synonyms() -> dict[str, str]:
    """Load synonym dictionary from JSON file, normalized keys."""
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
        normalized[normalize_text(key)] = value
    return normalized


# Alias for backward compatibility
_load_synonyms = load_synonyms


def get_fdc_connection() -> sqlite3.Connection:
    """Get SQLite connection for FDC database (singleton, thread-safe)."""
    global _conn, _synonyms
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is None:
            if not os.path.exists(DEFAULT_DB_PATH):
                raise FdcLookupError(f"FDC SQLite not found at {DEFAULT_DB_PATH}")
            _conn = sqlite3.connect(DEFAULT_DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _synonyms = load_synonyms()
    return _conn


# Alias for backward compatibility
_get_conn = get_fdc_connection


def _best_portion(portions: list[dict]) -> float | None:
    """Pick a representative gram weight for converting non-gram base units."""
    for p in portions:
        gram_weight = p.get("gram_weight")
        if gram_weight and gram_weight > 0:
            return gram_weight
    return None


def score_fdc_candidate(description: str, tokens: list[str]) -> float | None:
    """
    Score a candidate FDC match based on token containment and relevance.

    Returns None if token containment fails or blocklist hits.
    Higher score = better match.
    """
    normalized_desc = normalize_text(description)
    desc_tokens = normalized_desc.split()

    # Block obvious processed items unless explicitly asked (tokens contain the processed term)
    if any(b in desc_tokens for b in PROCESSED_BLOCKLIST) and not any(
        b in tokens for b in PROCESSED_BLOCKLIST
    ):
        return None

    def _token_matches(token: str, desc_token: str) -> bool:
        if desc_token == token:
            return True
        if desc_token.rstrip("s") == token or token.rstrip("s") == desc_token:
            return True
        if desc_token.endswith("es") and desc_token[:-2] == token:
            return True
        if token.endswith("es") and token[:-2] == desc_token:
            return True
        # Handle -y/-ies pluralization (cherry/cherries, berry/berries)
        if desc_token.endswith("ies") and token.endswith("y"):
            if desc_token[:-3] + "y" == token:
                return True
        if token.endswith("ies") and desc_token.endswith("y"):
            if token[:-3] + "y" == desc_token:
                return True
        return False

    def _contains(token: str) -> bool:
        return any(_token_matches(token, dt) for dt in desc_tokens)

    if not all(_contains(t) for t in tokens):
        return None

    match_count = len(tokens)
    extra_tokens = max(len(desc_tokens) - match_count, 0)
    score = match_count * 10 - extra_tokens * 0.5  # Increased penalty for extra tokens

    # Bonus if the first search token matches the first description token
    # This prioritizes "Cream, heavy" over "Coconut cream" when searching for "cream"
    if tokens and desc_tokens:
        first_token = tokens[0]
        first_desc = desc_tokens[0]
        if _token_matches(first_token, first_desc):
            score += 15  # Strong bonus for primary ingredient match

    if "raw" in desc_tokens:
        score += 3

    return score


# Alias for backward compatibility
_score_candidate = score_fdc_candidate


def get_data_type_weight(row: sqlite3.Row) -> int:
    """Get score weight bonus based on FDC data_type (foundation=6, sr_legacy=3, other=0)."""
    dt = (row["data_type"] or "").lower()
    if dt.startswith("foundation"):
        return 6
    if "sr_legacy" in dt:
        return 3
    return 0


# Alias for backward compatibility
_data_type_weight = get_data_type_weight


def _search(name: str, base_unit: str | None, allow_ascii: bool = False) -> list[sqlite3.Row]:
    conn = _get_conn()
    global _synonyms
    if not _synonyms:
        _synonyms = _load_synonyms()
    normalized = _normalize(name)
    synonyms_hit = _synonyms.get(normalized, normalized)
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
        score = score_fdc_candidate(r["description"], scoring_tokens)
        if score is None:
            continue
        score += get_data_type_weight(r)
        scored.append((score, r))

    # If raw hint filtered everything out, retry without it.
    if not scored and "raw" in scoring_tokens:
        scoring_tokens_no_raw = [t for t in scoring_tokens if t != "raw"]
        for r in rows:
            score = score_fdc_candidate(r["description"], scoring_tokens_no_raw)
            if score is None:
                continue
            score += get_data_type_weight(r)
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
