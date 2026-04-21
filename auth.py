import sqlite3
import hashlib
from database import Database
from repository import Repository
from models import User
from constants import VALID_ROLES

class AuthService:
    def __init__(self, repo: Repository, db: Database):
        self.repo = repo
        self.db = db

    def create_user(self, username: str, password: str, role: str):
        if role not in VALID_ROLES:
            raise Exception("Invalid role")

        cursor = self.db.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]

        if count == 0:
            role = "admin"

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                (username, password_hash, role)
            )
        except sqlite3.IntegrityError:
            raise Exception("User already exists")

        self.db.conn.commit()

    def login(self, username: str, password: str) -> User:
        cursor = self.db.conn.cursor()

        cursor.execute(
            "SELECT username, password_hash, role FROM users WHERE username=?",
            (username,)
        )

        row = cursor.fetchone()

        if not row:
            raise Exception("User not found")

        db_username, db_hash, role = row

        if db_hash != hashlib.sha256(password.encode()).hexdigest():
            raise Exception("Invalid password")

        return User(db_username, db_hash, role)