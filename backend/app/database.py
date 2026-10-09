import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from tenacity import retry, stop_after_attempt, wait_fixed

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://appuser:apppassword@db:5432/appdb"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@retry(stop=stop_after_attempt(15), wait=wait_fixed(2))
def wait_for_db():
    """Retry the connection until postgres is ready to accept connections."""
    conn = engine.connect()
    conn.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
