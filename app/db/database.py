from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args = {}
engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine_kwargs = {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_recycle=300,
    **engine_kwargs,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
