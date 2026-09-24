import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL, FALLBACK_SQLITE_URL

Base = declarative_base()

def get_engine():
    try:
        # Try connecting to PostgreSQL
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        conn = engine.connect()
        conn.close()
        print(f"Connected successfully to PostgreSQL database: {DATABASE_URL}")
        return engine
    except Exception as e:
        print(f"PostgreSQL connection failed ({e}). Falling back to SQLite database...")
        engine = create_engine(FALLBACK_SQLITE_URL, connect_args={"check_same_thread": False})
        return engine

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
