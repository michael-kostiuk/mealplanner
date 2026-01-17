from typing import Any, Optional

def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("'", "'").replace("’", "'").replace("`", "'")
    value = value.replace("“", "").replace("”", "").replace("'", "")
    value = value.replace(".", "")
    value = value.replace(",", "")
    value = " ".join(value.split())
    return value


def safe_parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip().replace(",", ".")
    if not s:
        return None
    if "/" in s and all(part.strip().replace(".", "", 1).isdigit() for part in s.split("/", 1)):
        num, den = s.split("/", 1)
        try:
            den_v = float(den)
            if den_v == 0:
                return None
            return float(num) / den_v
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def safe_parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return int(float(s.replace(",", ".")))
    except ValueError:
        return None
