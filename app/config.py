import os
from dataclasses import dataclass
from functools import lru_cache

REQUIRED_VARS = ("SESSION_SECRET", "OWNER_PIN_HASH", "OWNER_USER_ID")


@dataclass(frozen=True)
class Settings:
    session_secret: str
    owner_pin_hash: str
    owner_user_id: int
    cors_origins: list[str]
    cookie_secure: bool
    demo_db_path: str
    demo_seed_path: str
    dropbox_demo_folder: str


def load_settings() -> Settings:
    """Read settings from the environment; fail fast if a required secret is missing."""
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    try:
        owner_user_id = int(os.environ["OWNER_USER_ID"])
    except ValueError as e:
        raise RuntimeError("OWNER_USER_ID must be an integer") from e

    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return Settings(
        session_secret=os.environ["SESSION_SECRET"],
        owner_pin_hash=os.environ["OWNER_PIN_HASH"],
        owner_user_id=owner_user_id,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        cookie_secure=os.getenv("COOKIE_SECURE", "true").strip().lower() != "false",
        demo_db_path=os.getenv("DEMO_DB_PATH", "data/demo.sqlite"),
        demo_seed_path=os.getenv("DEMO_SEED_PATH", "app/demo/seed.json"),
        dropbox_demo_folder=os.getenv("DROPBOX_DEMO_FOLDER", "/recipes-demo"),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
