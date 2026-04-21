import socket
import json
import threading
import uuid

from repository import Repository
from database import Database
from auth import AuthService
from documents import DocumentService

HOST = "192.168.56.1"
PORT = 5000

repo = Repository()
db = Database(repo.path)
repo.db = db

auth = AuthService(repo, db)
doc_service = DocumentService(repo)

sessions = {}

ROLE_PERMISSIONS = {
    "admin": [
        "create-user",
        "create-document",
        "commit",
        "approve-version",
        "reject-version",
        "list-documents",
        "document-history",
        "active-version",
        "diff",
        "whoami"
    ],
    "author": [
        "create-document",
        "commit",
        "list-documents",
        "document-history",
        "active-version",
        "diff",
        "whoami"
    ],
    "reviewer": [
        "approve-version",
        "reject-version",
        "list-documents",
        "document-history",
        "active-version",
        "diff",
        "whoami"
    ],
    "reader": [
        "list-documents",
        "document-history",
        "active-version",
        "diff",
        "whoami"
    ]
}

def check_permission(user, command):
    allowed = ROLE_PERMISSIONS.get(user.role, [])
    return command in allowed

def handle_request(request):
    command = request.get("command")
    data = request.get("data", {})
    token = request.get("token")

    user = sessions.get(token)

    if command == "login":
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return {"status": "error", "error": "Missing credentials"}

        user = auth.login(username, password)

        token = str(uuid.uuid4())
        sessions[token] = user


        return {
                "status": "ok",
                "token": token,
                "data": {
                    "username": user.username,
                    "role": user.role
                }
            }

    if command == "create-user":
        if not user or user.role != "admin":
            return {"status": "error", "error": "Only admin can create users"}
        username = data.get("username")
        password = data.get("password")
        role = data.get("role")

        if not username or not password or not role:
            return {"status": "error", "error": "Missing fields"}

        auth.create_user(username, password, role)
        return {"status": "ok"}

    if not user:
        return {"status": "error", "error": "Not authenticated"}

    if command not in ["login", "create-user"]:
        if not check_permission(user, command):
            return {"status": "error", "error": "Access denied"}

    if command == "whoami":
        return {
            "status": "ok",
            "data": {
                "username": user.username,
                "role": user.role
            }
        }

    if command == "create-document":
        doc_id = doc_service.create_document(user, data["title"])
        return {"status": "ok", "data": doc_id}

    if command == "commit":
        commit_hash = doc_service.commit(user, data["message"], data["document"])
        if not commit_hash:
            return {"status": "error", "error": "No changes to commit"}

        return {"status": "ok", "data": commit_hash}

    if command == "list-documents":
        return {"status": "ok", "data": doc_service.list_documents()}

    if command == "document-history":
        return {"status": "ok", "data": doc_service.document_history(data["document"])}

    if command == "approve-version":
        doc_service.approve_version(user, data["document"], data["version"])
        return {"status": "ok"}

    if command == "reject-version":
        doc_service.reject_version(user, data["document"], data["version"])
        return {"status": "ok"}

    if command == "active-version":
        data = doc_service.show_active_version(data["document"])
        return {"status": "ok", "data": data}

    if command == "diff":
        result = doc_service.diff_versions(data["v1"], data["v2"])
        return {"status": "ok", "data": result}

    return {"status": "error", "error": "Unknown command"}

def handle_client(conn):
    try:
        request = json.loads(conn.recv(4096).decode())
        response = handle_request(request)
    except Exception as e:
        response = {"status": "error", "error": str(e)}

    conn.send(json.dumps(response).encode())
    conn.close()


def start():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    print("Server started...")

    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_client, args=(conn,)).start()


if __name__ == "__main__":
    start()