from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app import models
from app.auth.deps import AuthContext, get_auth
from app.database import get_db


def get_current_user(
    auth: Annotated[AuthContext, Depends(get_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    """The user row in the session's own DB (Postgres for the owner, SQLite for demo)."""
    return db.get(models.User, auth.user_id)
