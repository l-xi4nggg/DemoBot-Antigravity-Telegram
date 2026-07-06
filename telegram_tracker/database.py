from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from telegram_tracker.config import DATABASE_URL
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import ssl

# Setup sqlite specific options or pg8000 ssl_context
connect_args = {}
db_url = DATABASE_URL

if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif "pg8000" in db_url:
    parsed = urlparse(db_url)
    if parsed.query:
        query_params = parse_qs(parsed.query)
        has_ssl = False
        if "sslmode" in query_params:
            sslmode = query_params.get("sslmode")[0]
            if sslmode in ("require", "prefer", "allow"):
                has_ssl = True
        
        # Discard all query parameters to prevent TypeErrors in pg8000.connect
        db_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
            parsed.fragment
        ))
        
        if has_ssl:
            connect_args["ssl_context"] = ssl.create_default_context()

engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models in the application"""
    pass

@contextmanager
def get_db():
    """Context manager to ensure database sessions are closed correctly after use"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initializes the database and creates all tables"""
    # Import models here to register them with Base metadata
    from telegram_tracker.models.group import Group
    from telegram_tracker.models.user import User
    from telegram_tracker.models.record import Record
    from telegram_tracker.models.reminder import Reminder
    
    Base.metadata.create_all(bind=engine)
