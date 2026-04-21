import socket
import json
import argparse
import time
from pathlib import Path
from repository import Repository

HOST = "192.168.56.1"
PORT = 5000

SESSION_FILE = Path(".pygit/session")

def load_token():
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text().strip()
    return None


def save_token(token):
    SESSION_FILE.parent.mkdir(exist_ok=True)
    SESSION_FILE.write_text(token)


def send(command, data=None):
    token = load_token()

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect((HOST, PORT))

        request = {
            "command": command,
            "data": data or {},
            "token": token
        }

        client.send(json.dumps(request).encode())

        data_bytes = b""
        while True:
            part = client.recv(4096)
            if not part:
                break
            data_bytes += part

        response = json.loads(data_bytes.decode())

        if response.get("error") == "Not authenticated":
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()

        if "token" in response:
            save_token(response["token"])

        return response
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="PyGit Client")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize a new git repository")

    add_parser = subparsers.add_parser("add", help="Add files and directories to the index")
    add_parser.add_argument("paths", nargs="+", help="Files and directories to add")

    commit_parser = subparsers.add_parser("commit", help="Create a new commit")
    commit_parser.add_argument("-m", "--message", help="Commit message", required=True)
    commit_parser.add_argument("-d", "--document", required=True, help="Document ID")
    commit_parser.add_argument("--author", help="Author name and email")

    doc_parser = subparsers.add_parser("create-document", help="Create a new document")
    doc_parser.add_argument("-t", "--title", help="Document title", required=True)

    list_doc_parser = subparsers.add_parser("list-documents", help="List all documents")

    approve_parser = subparsers.add_parser("approve-version", help="Approve a document version")
    approve_parser.add_argument("-d", "--document", help="Document ID", required=True)
    approve_parser.add_argument("-v", "--version", help="Version", required=True)

    reject_parser = subparsers.add_parser("reject-version", help="Reject a document version")
    reject_parser.add_argument("-d", "--document", help="Document ID", required=True)
    reject_parser.add_argument("-v", "--version", help="Version", required=True)

    history_parser = subparsers.add_parser("document-history", help="Show document history")
    history_parser.add_argument("-d", "--document", help="Document ID", required=True)

    login_parser = subparsers.add_parser("login", help="Login to the repository")
    login_parser.add_argument("-u", "--username", help="Username", required=True)
    login_parser.add_argument("-p", "--password", help="Password", required=True)

    create_user_parser = subparsers.add_parser("create-user", help="Create a new user")
    create_user_parser.add_argument("-u", "--username", help="Username", required=True)
    create_user_parser.add_argument("-p", "--password", help="Password", required=True)
    create_user_parser.add_argument("-r", "--role", help="Role", required=True)

    whoami_parser = subparsers.add_parser("whoami", help="Show current user")

    active_parser = subparsers.add_parser("active-version", help="Show active version")
    active_parser.add_argument("-d", "--document", help="Document ID", required=True)

    diff_parser = subparsers.add_parser("diff", help="Compare two versions")
    diff_parser.add_argument("-v1", help="First commit", required=True)
    diff_parser.add_argument("-v2", help="Second commit", required=True)

    args = parser.parse_args()

    if args.command == "init":
        repo = Repository()

        if not repo.init():
            print("Repository already exists.")
        else:
            print("Repository initialized.")

    elif args.command == "add":
        repo = Repository()
        if not repo.git_dir.exists():
            print("Repository not initialized.")
            return

        for path in args.paths:
            try:
                repo.add_path(path)
            except Exception as e:
                print(f"Error: {e}")

    elif args.command == "login":
        res = send("login", {
            "username": args.username,
            "password": args.password
        })

        if res["status"] == "ok":
            print(f"Logged in as {res['data']['username']} ({res['data']['role']})")
        else:
            print(res["error"])


    elif args.command == "whoami":
        res = send("whoami")

        if res["status"] == "ok":
            data = res["data"]
            print("=== Current User ===")
            print(f"User: {data['username']}")
            print(f"Role: {data['role']}")
            print("====================")
        else:
            print(res["error"])

    elif args.command == "create-document":
        res = send("create-document", {"title": args.title})

        if res["status"] == "ok":
            print(f"Created document '{args.title}' with id {res['data']}")
        else:
            print(res["error"])

    elif args.command == "list-documents":
        res = send("list-documents")

        if res["status"] == "ok":
            data = res["data"]
            for doc in data:
                print(f"{doc['id']} - {doc['title']}")
        else:
            print(res["error"])

    elif args.command == "commit":
        res = send("commit",{
            "message": args.message,
            "document": args.document
        })

        if res["status"] == "ok":
            print(f"Created commit {res['data']} for document {args.document}")
        else:
            print(res["error"])

    elif args.command == "document-history":
        res = send("document-history", {"document": args.document})

        if res["status"] == "ok":
            data = res["data"]
            print(f"Document: {data['title']}")
            print(f"Active version: {data['active_version']}\n")

            for v in data["versions"]:
                print(f"{v['commit_hash']} - {v['status']} - {time.ctime(v['created_at'])} - {v['author']}")
        else:
            print(res["error"])

    elif args.command == "approve-version":
        res = send("approve-version", {
            "document": args.document,
            "version": args.version
        })

        if res["status"] == "ok":
            print(f"Version {args.version} approved")
        else:
            print(res["error"])

    elif args.command == "reject-version":
        res = send("reject-version", {
            "document": args.document,
            "version": args.version
        })

        if res["status"] == "ok":
            print(f"Version {args.version} rejected")
        else:
            print(res["error"])

    elif args.command == "active-version":
        res = send("active-version", {"document": args.document})

        if res["status"] == "ok":
            data = res["data"]

            print(f"Active version: {data['commit_hash']}")
            print(f"Message: {data['message']}")
            print(f"Author: {data['author']}")
            print(f"Date: {time.ctime(data['date'])}")

            print("\nFiles:")
            for f in data["files"]:
                print(f"  {f}")
        else:
            print(res["error"])

    elif args.command == "diff":
        res = send("diff", {
            "v1": args.v1,
            "v2": args.v2
        })

        if res["status"] == "ok":
            data = res["data"]
            for item in data:
                if item["type"] == "ADDED":
                    print(f"[ADDED] {item['file']}")

                elif item["type"] == "DELETED":
                    print(f"[DELETED] {item['file']}")

                elif item["type"] == "MODIFIED":
                    print(f"\n[MODIFIED] {item['file']}")

                    for change in item["changes"]:
                        print(f"Line {change['line']}:")
                        print(f"  - {change['old']}")
                        print(f"  + {change['new']}")
        else:
            print(res["error"])

    elif args.command == "create-user":
        res = send("create-user", {
            "username": args.username,
            "password": args.password,
            "role": args.role
        })

        if res["status"] == "ok":
            print(f"User '{args.username}' created with role '{args.role}'")
        else:
            print(res["error"])

    else:
        parser.print_help()

if __name__ == "__main__":
    main()