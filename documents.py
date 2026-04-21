import json
import time
import hashlib
from itertools import zip_longest
from repository import Repository
from models import User
from git_objects import Blob, Commit

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
