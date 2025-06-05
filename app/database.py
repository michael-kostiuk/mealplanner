from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

DATABASE_URL = "postgresql://postgres.pzieizznfcenhbamradg:#Gp4L#1l@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
#"postgresql://postgres:#Gp4L#1l@db.pzieizznfcenhbamradg.supabase.co:5432/postgres"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()