import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import re
from http.server import BaseHTTPRequestHandler, HTTPServer


DB_PATH = os.getenv("JELLOPASS_SYNC_DB", "jellopass_sync.db")
HOST = os.getenv("JELLOPASS_SYNC_HOST", "127.0.0.1")
PORT = int(os.getenv("JELLOPASS_SYNC_PORT", "8091"))
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
PBKDF2_ITERATIONS = 600_000
MAX_JSON_BODY_BYTES = 1_000_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS vaults (
                user_id INTEGER PRIMARY KEY,
                vault_data_b64 TEXT NOT NULL,
                key_data_b64 TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def hash_password(password, salt):
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return base64.b64encode(digest).decode("ascii")


def hash_session_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_json_body(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        return None
    if length <= 0 or length > MAX_JSON_BODY_BYTES:
        return None
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def create_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    now = int(time.time())
    expires_at = now + TOKEN_TTL_SECONDS
    conn.execute(
        "INSERT OR REPLACE INTO sessions(token, user_id, expires_at, created_at) VALUES(?, ?, ?, ?)",
        (token_hash, user_id, expires_at, now),
    )
    conn.commit()
    return token


def resolve_user_id_from_auth(header_value):
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value.split(" ", 1)[1].strip()
    if not token:
        return None
    token_hash = hash_session_token(token)
    now = int(time.time())
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        user_id, expires_at = row
        if expires_at < now:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
            conn.commit()
            return None
        return user_id
    finally:
        conn.close()


class SyncHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_OPTIONS(self):
        self._send_json(204, {})

    def do_POST(self):
        if self.path == "/register":
            return self.handle_register()
        if self.path == "/login":
            return self.handle_login()
        self._send_json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/vault":
            return self.handle_get_vault()
        self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        if self.path == "/vault":
            return self.handle_put_vault()
        self._send_json(404, {"error": "not found"})

    def handle_register(self):
        body = parse_json_body(self)
        if not body:
            self._send_json(400, {"error": "invalid json body"})
            return
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not USERNAME_PATTERN.fullmatch(username):
            self._send_json(400, {"error": "username must be 3-64 chars: letters, numbers, _, -, ."})
            return
        if len(password) < 8:
            self._send_json(400, {"error": "password must be at least 8 characters"})
            return
        salt = os.urandom(16)
        pwd_hash = hash_password(password, salt)
        now = int(time.time())
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users(username, password_salt, password_hash, created_at) VALUES(?, ?, ?, ?)",
                (username, base64.b64encode(salt).decode("ascii"), pwd_hash, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "username already exists"})
            return
        finally:
            conn.close()
        self._send_json(201, {"ok": True})

    def handle_login(self):
        body = parse_json_body(self)
        if not body:
            self._send_json(400, {"error": "invalid json body"})
            return
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not USERNAME_PATTERN.fullmatch(username):
            self._send_json(401, {"error": "invalid credentials"})
            return
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT id, password_salt, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row:
                self._send_json(401, {"error": "invalid credentials"})
                return
            user_id, salt_b64, stored_hash = row
            salt = base64.b64decode(salt_b64.encode("ascii"))
            computed = hash_password(password, salt)
            if not hmac.compare_digest(computed, stored_hash):
                self._send_json(401, {"error": "invalid credentials"})
                return
            token = create_session(conn, user_id)
            vault_row = conn.execute(
                "SELECT version FROM vaults WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            version = int(vault_row[0]) if vault_row else 0
        finally:
            conn.close()
        self._send_json(200, {"token": token, "vault_version": version})

    def _resolve_auth_user_id(self):
        return resolve_user_id_from_auth(self.headers.get("Authorization", ""))

    def handle_get_vault(self):
        user_id = self._resolve_auth_user_id()
        if not user_id:
            self._send_json(401, {"error": "unauthorized"})
            return
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT vault_data_b64, key_data_b64, version, updated_at FROM vaults WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            self._send_json(404, {"error": "vault not found"})
            return
        vault_data_b64, key_data_b64, version, updated_at = row
        self._send_json(
            200,
            {
                "vault_data_b64": vault_data_b64,
                "key_data_b64": key_data_b64,
                "vault_version": int(version),
                "updated_at": int(updated_at),
            },
        )

    def handle_put_vault(self):
        user_id = self._resolve_auth_user_id()
        if not user_id:
            self._send_json(401, {"error": "unauthorized"})
            return
        body = parse_json_body(self)
        if not body:
            self._send_json(400, {"error": "invalid json body"})
            return

        key_data_b64 = str(body.get("key_data_b64", ""))
        vault_data_b64 = str(body.get("vault_data_b64", ""))
        try:
            base_version = int(body.get("base_version", 0))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "base_version must be an integer"})
            return
        if not key_data_b64:
            self._send_json(400, {"error": "key_data_b64 is required"})
            return
        try:
            base64.b64decode(key_data_b64.encode("ascii"), validate=True)
            if vault_data_b64:
                base64.b64decode(vault_data_b64.encode("ascii"), validate=True)
        except Exception:
            self._send_json(400, {"error": "payload is not valid base64"})
            return

        now = int(time.time())
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT version FROM vaults WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current_version = int(row[0]) if row else 0
            if base_version != current_version:
                self._send_json(409, {"error": "version conflict", "vault_version": current_version})
                return
            new_version = current_version + 1
            conn.execute(
                """
                INSERT INTO vaults(user_id, vault_data_b64, key_data_b64, version, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    vault_data_b64=excluded.vault_data_b64,
                    key_data_b64=excluded.key_data_b64,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (user_id, vault_data_b64, key_data_b64, new_version, now),
            )
            conn.commit()
        finally:
            conn.close()
        self._send_json(200, {"ok": True, "vault_version": new_version})


def main():
    init_db()
    server = HTTPServer((HOST, PORT), SyncHandler)
    print(f"JelloPass sync server listening on {HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
