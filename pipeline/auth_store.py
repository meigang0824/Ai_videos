from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pipeline.config import STORAGE_DIR
from pipeline.database import create_app_engine, ensure_schema, users_table


AUTH_DB_PATH = STORAGE_DIR / "auth.sqlite3"
AUTH_SECRET_PATH = STORAGE_DIR / "auth_secret.key"
TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
PASSWORD_ITERATIONS = 260_000


def _now() -> int:
    return int(time.time())


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _load_secret() -> bytes:
    env_secret = os.getenv("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret.encode("utf-8")
    AUTH_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if AUTH_SECRET_PATH.exists():
        return AUTH_SECRET_PATH.read_bytes()
    secret = secrets.token_bytes(32)
    AUTH_SECRET_PATH.write_bytes(secret)
    return secret


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def _mapping(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def public_user(row: Any) -> dict[str, Any]:
    row = _mapping(row)
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


class AuthStore:
    def __init__(self, path: Path = AUTH_DB_PATH):
        self.path = path
        self.lock = threading.RLock()
        self.secret = _load_secret()
        self.engine = create_app_engine(path)
        ensure_schema(self.engine)

    def user_count(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(users_table)).scalar_one())

    def create_user(self, username: str, password: str, role: str | None = None) -> dict[str, Any]:
        username = username.strip()
        if len(username) < 3:
            raise ValueError("用户名至少需要 3 个字符")
        if len(password) < 8:
            raise ValueError("密码至少需要 8 个字符")
        role = role if role in {"admin", "user", "realtor"} else None
        with self.lock, self.engine.begin() as conn:
            assigned_role = role or ("admin" if self.user_count() == 0 else "user")
            user = {
                "id": uuid.uuid4().hex,
                "username": username,
                "password_hash": _hash_password(password),
                "role": assigned_role,
                "status": "active",
                "created_at": _now(),
                "last_login_at": None,
            }
            try:
                conn.execute(users_table.insert().values(**user))
            except IntegrityError as exc:
                raise ValueError("用户名已存在") from exc
            return public_user(user)

    def delete_user(self, user_id: str) -> bool:
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(select(users_table).where(users_table.c.id == user_id)).first()
            if not row:
                return False
            conn.execute(users_table.delete().where(users_table.c.id == user_id))
            return True

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(select(users_table).where(users_table.c.username == username.strip())).first()
            item = _mapping(row) if row else None
            if not item or item["status"] != "active":
                return None
            if not _verify_password(password, item["password_hash"]):
                return None
            conn.execute(users_table.update().where(users_table.c.id == item["id"]).values(last_login_at=_now()))
            refreshed = conn.execute(select(users_table).where(users_table.c.id == item["id"])).first()
            return public_user(refreshed)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(users_table).where(users_table.c.id == user_id)).first()
            item = _mapping(row) if row else None
            if not item or item["status"] != "active":
                return None
            return public_user(item)

    def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(users_table).order_by(users_table.c.created_at.desc()).limit(max(1, min(limit, 500)))
            ).fetchall()
            return [public_user(row) for row in rows]

    def issue_token(self, user: dict[str, Any]) -> str:
        payload = {
            "sub": user["id"],
            "username": user["username"],
            "role": user["role"],
            "iat": _now(),
            "exp": _now() + TOKEN_TTL_SECONDS,
        }
        body = _b64_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        signature = hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64_encode(signature)}"

    def verify_token(self, token: str) -> dict[str, Any] | None:
        try:
            body, signature = token.split(".", 1)
            expected = hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_b64_decode(signature), expected):
                return None
            payload = json.loads(_b64_decode(body).decode("utf-8"))
            if int(payload.get("exp") or 0) < _now():
                return None
            return self.get_user(str(payload.get("sub") or ""))
        except Exception:
            return None


auth_store = AuthStore()
