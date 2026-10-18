"""
app/services/chat_storage.py
===============================================================================
Lát 3 - Bước 2: Tầng lưu trữ SQLite riêng (`chat_state.db`). PRODUCT_SPEC Mục 8.1.

- File DB riêng, KHÔNG đụng `travel_db.db` (tránh khóa khi ghi).
- Đường dẫn: biến môi trường `CHAT_DB_PATH`, mặc định `./chat_state.db`. Được đọc ở MỖI lần kết nối
  (đổi biến môi trường là có hiệu lực ngay; test dùng `monkeypatch.setenv`).
- Mỗi lệnh gọi mở một kết nối riêng rồi đóng (an toàn với thread của FastAPI). Mỗi kết nối bật
  `journal_mode=WAL` và `foreign_keys=ON`, đồng thời `CREATE TABLE IF NOT EXISTS` (rẻ, tự phục hồi
  nếu file bị xóa).
- Module này CHỈ lo lưu/đọc: không băm mật khẩu, không gọi NLU, không import dialogue_models.
  Hợp đồng dữ liệu (Pydantic) nằm ở app/chat_models.py.

Quy ước kiểu dữ liệu trả về (dict thuần):
- `trip_request` và `payload` lưu dạng TEXT JSON, nhưng khi ĐỌC luôn được giải mã thành dict/list.
- Thời gian: chuỗi ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`).
- id: uuid4 dạng chuỗi.
"""
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Union

DEFAULT_DB_PATH = "./chat_state.db"
DB_PATH_ENV = "CHAT_DB_PATH"

ACTIVE_STATUSES = ("collecting", "ready")  # "đang dở": mỗi user tối đa MỘT phiên (Mục 8.1)
VALID_STATUSES = ("collecting", "ready", "planning", "planned", "error")  # Mục 4.4
VALID_ROLES = ("user", "assistant")


# ───────────────────────────────────────────────────────────────────────────────
# Lỗi
# ───────────────────────────────────────────────────────────────────────────────
class DuplicateEmailError(ValueError):
    """Email đã tồn tại (route nên đổi thành HTTP 409)."""


class UserNotFoundError(LookupError):
    """user_id không tồn tại."""


class SessionNotFoundError(LookupError):
    """session_id không tồn tại."""


# ───────────────────────────────────────────────────────────────────────────────
# Kết nối & schema
# ───────────────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id),
    status       TEXT NOT NULL,
    trip_request TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);

-- Ép ở mức DB: mỗi user tối đa MỘT phiên đang dở (chống race khi 2 request đồng thời).
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_one_active_per_user
    ON chat_sessions(user_id) WHERE status IN ('collecting', 'ready');

CREATE TABLE IF NOT EXISTS chat_messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);
"""


def get_db_path() -> str:
    path = os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH
    if path == ":memory:":
        # Mỗi lệnh gọi mở kết nối mới => ":memory:" sẽ là DB trống mỗi lần. Báo lỗi rõ thay vì lỗi ngầm.
        raise ValueError("CHAT_DB_PATH=':memory:' không được hỗ trợ; dùng đường dẫn file (vd. tmp_path).")
    return path


def _connect() -> sqlite3.Connection:
    path = get_db_path()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(_SCHEMA)
    return conn


def init_db() -> None:
    """Tạo file DB và 3 bảng nếu chưa có (gọi lúc khởi động app là tùy chọn; các hàm khác tự gọi)."""
    with closing(_connect()):
        pass


# ───────────────────────────────────────────────────────────────────────────────
# Tiện ích
# ───────────────────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def default_trip_request(session_id: str) -> dict:
    """Bản yêu cầu rỗng theo Mục 4 (status 'collecting'). Dùng cho phiên mới."""
    return {
        "session_id": session_id,
        "status": "collecting",
        "intent": "plan_itinerary",
        "critical": {"destination_mention": None, "origin_mention": None, "duration_days": None},
        "extra": {
            "group_size": None,
            "budget_total_vnd": None,
            "vehicle_type": None,
            "prefer_flight": None,
            "preferences": [],
            "pinned_mentions": [],
            "excluded_mentions": [],
            "excluded_activities": [],
        },
        "hints": {"destination_regions": [], "terrain_types": []},
        "asked": [],
        "turn": 0,
    }


def _user_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "created_at": row["created_at"],
    }


def _session_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "trip_request": json.loads(row["trip_request"]),
        "updated_at": row["updated_at"],
    }


def _message_row(row: sqlite3.Row) -> dict:
    payload = row["payload"]
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "payload": None if payload is None else json.loads(payload),
        "created_at": row["created_at"],
    }


def _normalize_email(email: str) -> str:
    return email.strip().lower()


# ───────────────────────────────────────────────────────────────────────────────
# Users
# ───────────────────────────────────────────────────────────────────────────────
def create_user(email: str, password_hash: str) -> dict:
    """Tạo user. Email được lưu chữ thường (Mục 3.2). Trùng email -> DuplicateEmailError.
    `password_hash` phải là hash đã băm (bcrypt/argon2); module này không băm."""
    email = _normalize_email(email)
    if not email:
        raise ValueError("email không được để trống")
    if not password_hash:
        raise ValueError("password_hash không được để trống")
    user_id, created_at = _new_id(), _now()
    with closing(_connect()) as conn:
        try:
            with conn:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, email, password_hash, created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEmailError(f"email đã tồn tại: {email}") from exc
    return {"id": user_id, "email": email, "password_hash": password_hash, "created_at": created_at}


def get_user_by_email(email: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (_normalize_email(email),)).fetchone()
    return _user_row(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_row(row) if row else None


# ───────────────────────────────────────────────────────────────────────────────
# Sessions
# ───────────────────────────────────────────────────────────────────────────────
def _select_active_session(conn: sqlite3.Connection, user_id: str) -> Optional[sqlite3.Row]:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    return conn.execute(
        f"SELECT * FROM chat_sessions WHERE user_id = ? AND status IN ({placeholders}) "
        "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
        (user_id, *ACTIVE_STATUSES),
    ).fetchone()


def get_or_create_active_session(user_id: str) -> dict:
    """Trả phiên đang dở ('collecting' / 'ready') của user; chưa có thì tạo phiên 'collecting' mới.
    Mỗi user tối đa một phiên đang dở (ép bằng unique index một phần). user_id lạ -> UserNotFoundError."""
    with closing(_connect()) as conn:
        row = _select_active_session(conn, user_id)
        if row:
            return _session_row(row)
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
            raise UserNotFoundError(f"không có user: {user_id}")
        session_id = _new_id()
        trip_request = default_trip_request(session_id)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO chat_sessions (id, user_id, status, trip_request, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, user_id, "collecting", _dumps(trip_request), _now()),
                )
        except sqlite3.IntegrityError:
            # Request song song đã tạo phiên trước ta: lấy phiên đó.
            row = _select_active_session(conn, user_id)
            if row:
                return _session_row(row)
            raise
        return _session_row(conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone())


def get_session_by_id(session_id: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_row(row) if row else None


def update_session_trip_request(
    session_id: str, trip_request_json: Union[str, Mapping[str, Any]], status: str
) -> None:
    """Ghi đè bản yêu cầu + status của phiên và cập nhật updated_at.
    `trip_request_json`: chuỗi JSON (object) hoặc dict. Sai status/JSON -> ValueError.
    Phiên không tồn tại -> SessionNotFoundError."""
    if status not in VALID_STATUSES:
        raise ValueError(f"status không hợp lệ: {status!r}")
    if isinstance(trip_request_json, str):
        try:
            parsed = json.loads(trip_request_json)
        except json.JSONDecodeError as exc:
            raise ValueError("trip_request_json không phải JSON hợp lệ") from exc
    else:
        parsed = dict(trip_request_json)
    if not isinstance(parsed, dict):
        raise ValueError("trip_request phải là một JSON object")
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute(
                "UPDATE chat_sessions SET status = ?, trip_request = ?, updated_at = ? WHERE id = ?",
                (status, _dumps(parsed), _now(), session_id),
            )
        if cur.rowcount == 0:
            raise SessionNotFoundError(f"không có phiên: {session_id}")


# ───────────────────────────────────────────────────────────────────────────────
# Messages
# ───────────────────────────────────────────────────────────────────────────────
def add_chat_message(session_id: str, role: str, content: str, payload: Optional[Any] = None) -> dict:
    """Thêm tin nhắn (role 'user'|'assistant'). `payload` (tùy chọn, vd. {"chips": [...]}) lưu dạng JSON.
    Phiên không tồn tại -> SessionNotFoundError. Đồng thời cập nhật updated_at của phiên."""
    if role not in VALID_ROLES:
        raise ValueError(f"role không hợp lệ: {role!r}")
    if not isinstance(content, str):
        raise ValueError("content phải là chuỗi")
    message_id, created_at = _new_id(), _now()
    payload_text = None if payload is None else _dumps(payload)
    with closing(_connect()) as conn:
        try:
            with conn:
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (message_id, session_id, role, content, payload_text, created_at),
                )
                conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (created_at, session_id))
        except sqlite3.IntegrityError as exc:
            raise SessionNotFoundError(f"không có phiên: {session_id}") from exc
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "payload": None if payload is None else json.loads(payload_text),
        "created_at": created_at,
    }


def get_session_messages(session_id: str) -> List[dict]:
    """Tin nhắn của phiên, tăng dần theo created_at (cùng thời điểm thì theo thứ tự chèn)."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
            (session_id,),
        ).fetchall()
    return [_message_row(r) for r in rows]


__all__ = [
    "DEFAULT_DB_PATH", "DB_PATH_ENV", "ACTIVE_STATUSES", "VALID_STATUSES", "VALID_ROLES",
    "DuplicateEmailError", "UserNotFoundError", "SessionNotFoundError",
    "get_db_path", "init_db", "default_trip_request",
    "create_user", "get_user_by_email", "get_user_by_id",
    "get_or_create_active_session", "get_session_by_id", "update_session_trip_request",
    "add_chat_message", "get_session_messages",
]
