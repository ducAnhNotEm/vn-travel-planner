import os
from dotenv import load_dotenv

load_dotenv()

# Database Connection Settings: Thuần SQLite 100% (travel_db.db)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./travel_db.db")
