import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")

# Check if a token was passed as a command-line argument
cli_token = sys.argv[1] if len(sys.argv) > 1 and ":" in sys.argv[1] else None

if cli_token:
    TELEGRAM_BOT_TOKEN = cli_token
    # Automatically derive the database file name from the bot's ID (first part of token)
    bot_id = cli_token.split(":")[0]
    DEFAULT_DB_PATH = BASE_DIR / "database" / f"tracker_{bot_id}.db"
    DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
else:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    DEFAULT_DB_PATH = BASE_DIR / "database" / "tracker.db"
    raw_db_url = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif raw_db_url.startswith("postgresql://"):
        raw_db_url = raw_db_url.replace("postgresql://", "postgresql+pg8000://", 1)
    DATABASE_URL = raw_db_url

# Ensure database directory exists if using local SQLite database
if DATABASE_URL.startswith("sqlite:///"):
    db_path_str = DATABASE_URL.replace("sqlite:///", "")
    db_file_path = Path(db_path_str)
    # If the path is relative, resolve it relative to base directory
    if not db_file_path.is_absolute():
        db_file_path = (BASE_DIR / db_file_path).resolve()
    
    # Re-normalize DATABASE_URL to use the absolute path
    DATABASE_URL = f"sqlite:///{db_file_path.as_posix()}"
    
    if os.getenv("VERCEL"):
        raise ValueError(
            "SQLite database is not supported on Vercel serverless (read-only filesystem). "
            "Please ensure you configured 'DATABASE_URL' in your Vercel Project Settings to point to your Neon PostgreSQL database."
        )
        
    try:
        db_file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
