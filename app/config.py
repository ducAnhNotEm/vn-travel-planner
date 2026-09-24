import os
from dotenv import load_dotenv

load_dotenv()

# Database Connection Settings
# Default PostgreSQL URL: postgresql://postgres:postgrespassword@localhost:5432/travel_db
# Fallback to SQLite if PostgreSQL is not available locally
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/travel_db")
FALLBACK_SQLITE_URL = "sqlite:///./travel_db.db"
