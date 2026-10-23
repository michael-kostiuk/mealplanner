from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.auth.deps import AuthContext, forget_user, get_auth
from app.database import get_db


def get_current_user(
    auth: Annotated[AuthContext, Depends(get_auth)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    """The user row in the session's own DB (Postgres for the owner, SQLite for demo)."""
    user = db.get(models.User, auth.user_id)
    if user is None:
        # Cached owner row deleted, or demo DB without its user: drop the stale cache entry
        forget_user(auth.user_id)
        raise HTTPException(status_code=401, detail="User not found")
    return user
