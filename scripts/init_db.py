"""Create the SQLite schema. Usage: python -m scripts.init_db"""
from solesight import db, config

if __name__ == "__main__":
    db.init_db()
    print(f"Initialized database at {config.DB_PATH}")
