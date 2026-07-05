from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from telegram_tracker.config import DATABASE_URL

# Setup sqlite specific options
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
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
