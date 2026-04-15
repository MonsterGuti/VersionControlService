from __future__ import annotations
import sqlite3
import hashlib
import json
from pathlib import Path
import time
from typing import Dict, List
from itertools import zip_longest
import zlib

VALID_ROLES = ["author", "reviewer", "reader", 'admin']

class Database:
    def __init__(self, repo_path: Path):
        self.db_path = repo_path / ".pygit" / "database"
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")

class GitObject:
    def __init__(self, obj_type: str, content: bytes):
        self.type = obj_type
        self.content = content

    def hash(self) -> str:
        header = f"{self.type} {len(self.content)}\0".encode()
        return hashlib.sha1(header + self.content).hexdigest()

    def serialize(self) -> bytes:
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header + self.content)

    @classmethod
    def deserialize(cls, data: bytes) -> GitObject:
        decompressed = zlib.decompress(data)
        # search in binary data
        null_index = decompressed.find(b"\0")
        header = decompressed[:null_index].decode()
        content = decompressed[null_index + 1:]
        obj_type, size = header.split(" ")
        return cls(obj_type, content)

class Blob(GitObject):
    def __init__(self, content: bytes):
        super().__init__("blob", content)

class Commit(GitObject):
    def __init__(self, tree_hash: str, parent_hashes: List[str], author: str, committer: str, message: str, timestamp: int = None):
        self.tree_hash = tree_hash
        self.parent_hashes = parent_hashes
        self.author = author
        self.committer = committer
        self.message = message
        self.timestamp = timestamp or int(time.time())
        content = self.serialize_commit()
        super().__init__("commit", content)

    def serialize_commit(self):
        lines = [f"tree {self.tree_hash}"]
        for parent_hash in self.parent_hashes:
            lines.append(f"parent {parent_hash}")
        lines.append(f"author {self.author} {self.timestamp} +0000")
        lines.append(f"committer {self.committer} {self.timestamp} +0000")
        lines.append("")
        lines.append(self.message)

        return "\n".join(lines).encode()

    @classmethod
    def from_content(cls, content: bytes) -> Commit:
        lines = content.decode().split("\n")
        tree_hash = None
        parent_hashes = []
        author = None
        committer = None
        message_start = 0

        for i, line in enumerate(lines):
            if line.startswith("tree "):
                tree_hash = line[5:]
            elif line.startswith("parent "):
                parent_hashes.append(line[7:])
            elif line.startswith("author "):
                author_parts = line[7:].rsplit(" ", 2)
                author = author_parts[0]
                timestamp = int(author_parts[1])
            elif line.startswith("committer "):
                commiter_parts = line[10:].rsplit(" ", 2)
                committer = commiter_parts[0]
            elif line == "":
                message_start = i + 1
                break

        message = "\n".join(lines[message_start:])

        commit = cls(tree_hash, parent_hashes, author, committer, message, timestamp)
        return commit

class User:
    def __init__(self, username: str, password_hash: str, role: str):
        self.username = username
        self.password_hash = password_hash
        self.role = role

class Repository:
    def __init__(self, path = "."):
        self.path = Path(path).resolve()
        self.git_dir = self.path / ".pygit"

        self.objects_dir = self.git_dir / "objects"

        self.index_file = self.git_dir / "index"

    def init(self) -> bool:
        if self.git_dir.exists():
            return False

        self.git_dir.mkdir()
        self.objects_dir.mkdir()

        self.save_index({})

        print(f"Initialized git repository in {self.git_dir}")

        return True

    def load_object(self, obj_hash: str) -> GitObject:
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found")

        return GitObject.deserialize(obj_file.read_bytes())

    def store_object(self, obj: GitObject) -> str:
        obj_hash = obj.hash()
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            obj_dir.mkdir(exist_ok=True)
            obj_file.write_bytes(obj.serialize())

        return obj_hash

    def load_index(self) -> Dict[str, str]:
        if not self.index_file.exists():
            return {}

        try:
            return json.loads(self.index_file.read_text())
        except:
            return {}

    def save_index(self, index: Dict[str, str]):
        self.index_file.write_text(json.dumps(index, indent=2))

    def add_file(self, path: str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")

        content = full_path.read_bytes()

        blob = Blob(content)

        blob_hash = self.store_object(blob)

        index = self.load_index()
        index[path] = blob_hash
        self.save_index(index)

        print(f"Added {path}")

    def add_directory(self, path: str):
        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Directory {path} not found")

        if not full_path.is_dir():
            raise ValueError(f"{path} is not a directory")

        index = self.load_index()
        added_count = 0

        for file_path in full_path.rglob("*"):
            if file_path.is_file():
                if ".pygit" in file_path.parts or ".idea" in file_path.parts:
                    continue

                content = file_path.read_bytes()
                blob = Blob(content)
                blob_hash = self.store_object(blob)

                relative_path = str(file_path.relative_to(self.path))
                index[relative_path] = blob_hash
                added_count += 1

        self.save_index(index)

        if added_count > 0:
            print(f"Added {added_count} files from directory {path}")
        else:
            print(f"Directory {path} is up to date")

    def add_path(self, path: str) -> None:
        full_path = self.path / path

        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")

        if full_path.is_file():
            self.add_file(path)
        elif full_path.is_dir():
            self.add_directory(path)
        else:
            raise ValueError(f"Path {path} is not a file or directory")

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

class DocumentService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def commit(self, user: User, message: str, document_id: str):
        cursor = self.repo.db.conn.cursor()

        cursor.execute("SELECT id FROM documents WHERE id=?", (document_id,))
        if not cursor.fetchone():
            raise Exception("Document not found")

        index = self.repo.load_index()

        if not index:
            raise Exception("No changes to commit")

        snapshot_content = json.dumps(index, indent=2).encode()
        snapshot_blob = Blob(snapshot_content)
        snapshot_hash = self.repo.store_object(snapshot_blob)

        parent_hashes = []

        cursor.execute("""
                       SELECT commit_hash
                       FROM versions
                       WHERE document_id = ?
                       ORDER BY created_at DESC
                       LIMIT 1
                       """, (document_id,))

        row = cursor.fetchone()

        if row:
            parent_hashes.append(row[0])

            last_commit_obj = self.repo.load_object(row[0])
            last_commit = Commit.from_content(last_commit_obj.content)

            if last_commit.tree_hash == snapshot_hash:
                raise Exception("No changes to commit")

        author = user.username
        commit = Commit(snapshot_hash, parent_hashes, author, author, message)
        commit_hash = self.repo.store_object(commit)

        cursor.execute("""
                       INSERT INTO versions (commit_hash, document_id, status, created_at, author)
                       VALUES (?, ?, ?, ?, ?)
                       """, (
                           commit_hash,
                           document_id,
                           "DRAFT",
                           int(time.time()),
                           user.username
                       ))

        self.repo.db.conn.commit()
        self.repo.save_index({})

        return commit_hash

    def create_document(self, user: User, title: str) -> str:
        doc_id = hashlib.sha1((title + str(time.time())).encode()).hexdigest()[:8]

        cursor = self.repo.db.conn.cursor()

        cursor.execute(
            "INSERT INTO documents (id, title, active_version) VALUES (?, ?, ?)",
            (doc_id, title, None)
        )

        self.repo.db.conn.commit()

        return doc_id

    def list_documents(self):
        cursor = self.repo.db.conn.cursor()

        return [
            {"id": row[0], "title": row[1]}
            for row in cursor.execute("SELECT id, title FROM documents")
        ]

    def document_history(self, document_id: str):
        cursor = self.repo.db.conn.cursor()

        cursor.execute(
            "SELECT title, active_version FROM documents WHERE id=?",
            (document_id,)
        )

        doc = cursor.fetchone()

        if not doc:
            raise Exception("Document not found")

        cursor.execute("""
                       SELECT commit_hash, status, created_at, author
                       FROM versions
                       WHERE document_id = ?
                       ORDER BY created_at DESC
                       """, (document_id,))

        return {
            "title": doc[0],
            "active_version": doc[1],
            "versions": [
                {
                    "commit_hash": v[0],
                    "status": v[1],
                    "created_at": v[2],
                    "author": v[3]
                }
                for v in cursor.fetchall()
            ]
        }

    def approve_version(self, user: User, document_id: str, commit_hash: str):
        cursor = self.repo.db.conn.cursor()

        cursor.execute("""
                       SELECT status
                       FROM versions
                       WHERE commit_hash = ?
                         AND document_id = ?
                       """, (commit_hash, document_id))

        row = cursor.fetchone()

        if not row:
            raise Exception("Version not found")

        if row[0] != "DRAFT":
            raise Exception("Only DRAFT can be approved")

        cursor.execute("""
                       UPDATE versions
                       SET status='APPROVED',
                           approved_by=?,
                           approved_at=?
                       WHERE commit_hash = ?
                       """, (
                           user.username,
                           int(time.time()),
                           commit_hash
                       ))

        cursor.execute("""
                       UPDATE documents
                       SET active_version=?
                       WHERE id = ?
                       """, (commit_hash, document_id))

        self.repo.db.conn.commit()

    def reject_version(self, user: User, document_id: str, commit_hash: str):
        cursor = self.repo.db.conn.cursor()

        cursor.execute("""
                       SELECT status
                       FROM versions
                       WHERE commit_hash = ?
                         AND document_id = ?
                       """, (commit_hash, document_id))

        row = cursor.fetchone()

        if not row:
            raise Exception("Version not found")

        if row[0] != "DRAFT":
            raise Exception("Only DRAFT can be rejected")

        cursor.execute("""
                       UPDATE versions
                       SET status='REJECTED'
                       WHERE commit_hash = ?
                         AND document_id = ?
                       """, (commit_hash, document_id))

        self.repo.db.conn.commit()

    def show_active_version(self, document_id: str):
        cursor = self.repo.db.conn.cursor()

        cursor.execute(
            "SELECT active_version FROM documents WHERE id=?",
            (document_id,)
        )

        row = cursor.fetchone()

        if not row:
            raise Exception("Document not found")

        if not row[0]:
            raise Exception("No active version")


        commit_hash = row[0]

        commit_obj = self.repo.load_object(commit_hash)
        commit = Commit.from_content(commit_obj.content)


        snapshot = self.repo.load_object(commit.tree_hash)
        files = json.loads(snapshot.content.decode())

        return {
            "commit_hash": commit_hash,
            "message": commit.message,
            "author": commit.author,
            "date": commit.timestamp,
            "files": list(files.keys())
        }

    def diff_versions(self, commit1: str, commit2: str):
        obj1 = self.repo.load_object(commit1)
        obj2 = self.repo.load_object(commit2)

        c1 = Commit.from_content(obj1.content)
        c2 = Commit.from_content(obj2.content)

        snap1 = self.repo.load_object(c1.tree_hash)
        snap2 = self.repo.load_object(c2.tree_hash)

        files1 = json.loads(snap1.content.decode())
        files2 = json.loads(snap2.content.decode())

        all_files = set(files1.keys()) | set(files2.keys())

        result = []
        for f in sorted(all_files):
            h1 = files1.get(f)
            h2 = files2.get(f)

            if h1 is None:
                result.append({"type": "ADDED", "file": f})
                continue

            if h2 is None:
                result.append({"type": "DELETED", "file": f})
                continue

            if h1 != h2:
                blob1 = self.repo.load_object(h1)
                blob2 = self.repo.load_object(h2)

                old_lines = blob1.content.decode(errors="ignore").splitlines()
                new_lines = blob2.content.decode(errors="ignore").splitlines()

                changes = []
                for i, (old, new) in enumerate(zip_longest(old_lines, new_lines), start=1):
                    if old != new:
                        changes.append({
                            "line": i,
                            "old": old,
                            "new": new
                        })

                result.append({
                    "type": "MODIFIED",
                    "file": f,
                    "changes": changes
                })

        return result
