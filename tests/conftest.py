import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_medinote.db")
os.environ.setdefault("MOCK_AI", "true")
os.environ.setdefault("SEED_ON_STARTUP", "false")
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "10000")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PDF_OUTPUT_DIR", "test_pdfs")
os.environ.setdefault("AUDIO_OUTPUT_DIR", "test_audio")

from app.core.config import get_settings

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    from app.db.database import Base, engine
    from app.db.seed import ensure_auth_credentials, seed_database

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        seed_database(db)
        ensure_auth_credentials(db)
    finally:
        db.close()

    yield

    Base.metadata.drop_all(bind=engine)
    get_settings.cache_clear()
