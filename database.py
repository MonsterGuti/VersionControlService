import sqlite3
from pathlib import Path

class Database:
    def __init__(self, repo_path: Path):
        self.db_path = repo_path / ".pygit" / "database"
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")