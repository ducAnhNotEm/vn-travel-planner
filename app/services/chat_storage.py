"""
app/services/chat_storage.py
===============================================================================
Lát 3 - Bước 2: Tầng lưu trữ SQLite riêng (`chat_state.db`). PRODUCT_SPEC Mục 8.1.
Nâng cấp: Optimistic Concurrency Control (CAS version), commit_turn nguyên tử,
và phân quyền tại tầng repository (A1, A2, A5, A6, C1).

- File DB riêng, KHÔNG đụng `travel_db.db` (tránh khóa khi ghi).
- Đường dẫn: biến môi trường `CHAT_DB_PATH`, mặc định `./chat_state.db`. Được đọc ở MỖI lần kết nối
  (đổi biến môi trường là có hiệu lực ngay; test dùng `monkeypatch.setenv`).
- Mỗi kết nối bật `journal_mode=WAL` và `foreign_keys=ON`. Schema được khởi tạo 1 lần theo đường dẫn.
- Quản lý phiên có cột `version INTEGER NOT NULL DEFAULT 1` hỗ trợ CAS chống lost update.
- Bảng `chat_messages` có cột `seq INTEGER PRIMARY KEY AUTOINCREMENT` bảo đảm thứ tự chèn đơn điệu.
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
from typing import Any, List, Mapping, Optional, Tuple, Union

DEFAULT_DB_PATH = "./chat_state.db"
DB_PATH_ENV = "CHAT_DB_PATH"

ACTIVE_STATUSES = ("collecting", "ready")  # "đang dở": mỗi user tối đa MỘT phiên (Mục 8.1)
VALID_STATUSES = ("collecting", "ready", "planning", "planned", "error")  # Mục 4.4
VALID_ROLES = ("user", "assistant")

_INITIALIZED_PATHS = set()


# ───────────────────────────────────────────────────────────────────────────────
# Lỗi
# ───────────────────────────────────────────────────────────────────────────────
class DuplicateEmailError(ValueError):
    """Email đã tồn tại (route nên đổi thành HTTP 409)."""


class UserNotFoundError(LookupError):
    """user_id không tồn tại."""


class SessionNotFoundError(LookupError):
    """session_id không tồn tại."""


class StaleSessionError(RuntimeError):
    """Phiên đã bị thay đổi bởi luồng/tiến trình khác (CAS version hoặc status không khớp)."""


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
    version      INTEGER NOT NULL DEFAULT 1,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id);

-- Ép ở mức DB: mỗi user tối đa MỘT phiên đang dở (chống race khi 2 request đồng thời).
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_one_active_per_user
    ON chat_sessions(user_id) WHERE status IN ('collecting', 'ready');

CREATE TABLE IF NOT EXISTS chat_messages (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    id         TEXT UNIQUE NOT NULL,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    payload    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq ON chat_messages(session_id, seq);

-- Bước 3: token đăng nhập. Chỉ lưu SHA-256 của token (lộ DB không lộ token dùng được).
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at);
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
    conn.execute("PRAGMA foreign_keys=ON;")

    has_tables = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if not has_tables:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SCHEMA)
    return conn



def init_db() -> None:
    """Tạo file DB và các bảng nếu chưa có (chạy lúc khởi động ứng dụng)."""
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
    version = row["version"] if "version" in row.keys() else 1
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "trip_request": json.loads(row["trip_request"]),
        "version": version,
        "updated_at": row["updated_at"],
    }


def _message_row(row: sqlite3.Row) -> dict:
    payload = row["payload"]
    seq = row["seq"] if "seq" in row.keys() else None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "payload": None if payload is None else json.loads(payload),
        "created_at": row["created_at"],
        "seq": seq,
    }


def _normalize_email(email: str) -> str:
    return email.strip().lower()


# ───────────────────────────────────────────────────────────────────────────────
# Users
# ───────────────────────────────────────────────────────────────────────────────
def create_user(email: str, password_hash: str) -> dict:
    """Tạo user. Email được lưu chữ thường (Mục 3.2). Trùng email -> DuplicateEmailError."""
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
    """Trả phiên đang dở ('collecting' / 'ready') của user; chưa có thì tạo phiên 'collecting' mới (version=1).
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
                    "INSERT INTO chat_sessions (id, user_id, status, trip_request, version, updated_at) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (session_id, user_id, "collecting", _dumps(trip_request), _now()),
                )
        except sqlite3.IntegrityError:
            # Request song song đã tạo phiên trước ta: lấy phiên đó.
            row = _select_active_session(conn, user_id)
            if row:
                return _session_row(row)
            raise
        return _session_row(conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone())


def get_session_by_id(session_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Lấy phiên chat theo session_id. Nếu truyền user_id, lọc thêm user_id để phân quyền."""
    with closing(_connect()) as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_row(row) if row else None


def get_session_for_user(session_id: str, user_id: str) -> Optional[dict]:
    """Helper phân quyền: lấy phiên chat chỉ khi thuộc quyền sở hữu của user_id."""
    return get_session_by_id(session_id, user_id=user_id)


def update_session_trip_request(
    session_id: str,
    trip_request_json: Union[str, Mapping[str, Any]],
    status: str,
    expected_version: Optional[int] = None,
    user_id: Optional[str] = None,
) -> int:
    """Ghi đè bản yêu cầu + status của phiên và cập nhật updated_at.
    Nếu truyền `expected_version`, thực thi CAS (Optimistic Locking): tăng version = version + 1
    và ném `StaleSessionError` nếu phiên đã bị thay đổi trước đó. Trả về version mới của phiên."""
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

    now = _now()
    with closing(_connect()) as conn:
        with conn:
            if expected_version is not None:
                sql = (
                    "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? "
                    "WHERE id = ? AND version = ?"
                )
                params: List[Any] = [status, _dumps(parsed), now, session_id, expected_version]
                if user_id:
                    sql += " AND user_id = ?"
                    params.append(user_id)
                cur = conn.execute(sql, tuple(params))
                if cur.rowcount == 0:
                    sess = conn.execute("SELECT user_id, version FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
                    if sess is None:
                        raise SessionNotFoundError(f"không có phiên: {session_id}")
                    if user_id and sess["user_id"] != user_id:
                        raise PermissionError(f"user {user_id} không sở hữu phiên {session_id}")
                    raise StaleSessionError(
                        f"Phiên {session_id} đã thay đổi: version hiện tại={sess['version']}, mong đợi={expected_version}"
                    )
                return None
            else:
                cur = conn.execute(
                    "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? "
                    "WHERE id = ?",
                    (status, _dumps(parsed), now, session_id),
                )
                if cur.rowcount == 0:
                    raise SessionNotFoundError(f"không có phiên: {session_id}")
                return None



def commit_turn(
    session_id: str,
    user_id: str,
    expected_version: int,
    new_status: str,
    trip_request_json: Union[str, Mapping[str, Any]],
    messages: List[Mapping[str, Any]],
) -> Tuple[dict, List[dict]]:
    """Ghi nguyên tử toàn bộ một lượt tương tác (state change + messages) bằng transaction BEGIN IMMEDIATE.
    
    1. Kiểm tra session thuộc về user_id và có version == expected_version (CAS).
    2. Cập nhật status, trip_request, tăng version = version + 1, updated_at.
    3. Thêm các tin nhắn (user & assistant) trong cùng transaction.
    4. Nếu version hoặc status không khớp -> rollback và ném StaleSessionError.
    5. Nếu session không tồn tại -> rollback và ném SessionNotFoundError.
    6. Nếu user_id không khớp -> rollback và ném PermissionError.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"status không hợp lệ: {new_status!r}")
    if isinstance(trip_request_json, str):
        try:
            parsed_trip = json.loads(trip_request_json)
        except json.JSONDecodeError as exc:
            raise ValueError("trip_request_json không phải JSON hợp lệ") from exc
    else:
        parsed_trip = dict(trip_request_json)
    if not isinstance(parsed_trip, dict):
        raise ValueError("trip_request phải là một JSON object")

    for msg in messages:
        if msg.get("role") not in VALID_ROLES:
            raise ValueError(f"role không hợp lệ: {msg.get('role')!r}")
        if not isinstance(msg.get("content"), str):
            raise ValueError("content phải là chuỗi")

    now = _now()
    with closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            sess = conn.execute(
                "SELECT id, user_id, status, version FROM chat_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if sess is None:
                raise SessionNotFoundError(f"không có phiên: {session_id}")
            if sess["user_id"] != user_id:
                raise PermissionError(f"user {user_id} không có quyền truy cập phiên {session_id}")
            if sess["version"] != expected_version:
                raise StaleSessionError(
                    f"Phiên {session_id} đã thay đổi: version hiện tại={sess['version']}, mong đợi={expected_version}"
                )

            cur = conn.execute(
                "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? "
                "WHERE id = ? AND user_id = ? AND version = ?",
                (new_status, _dumps(parsed_trip), now, session_id, user_id, expected_version),
            )
            if cur.rowcount == 0:
                raise StaleSessionError(f"CAS thất bại trên phiên {session_id}")

            created_messages = []
            for msg in messages:
                msg_id = msg.get("id") or _new_id()
                role = msg["role"]
                content = msg["content"]
                payload = msg.get("payload")
                payload_text = None if payload is None else _dumps(payload)
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (msg_id, session_id, role, content, payload_text, now),
                )
                created_messages.append({
                    "id": msg_id,
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "payload": payload,
                    "created_at": now,
                })

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        updated_session = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        return _session_row(updated_session), created_messages


# ───────────────────────────────────────────────────────────────────────────────
# Messages
# ───────────────────────────────────────────────────────────────────────────────
def add_chat_message(session_id: str, role: str, content: str, payload: Optional[Any] = None) -> dict:
    """Thêm tin nhắn đơn lẻ (role 'user'|'assistant').
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


def get_session_messages(session_id: str, user_id: Optional[str] = None) -> List[dict]:
    """Tin nhắn của phiên, tăng dần theo created_at ASC, seq ASC.
    Nếu truyền `user_id`, kiểm tra quyền sở hữu trước khi đọc; nếu không thuộc user -> ném PermissionError."""
    with closing(_connect()) as conn:
        if user_id is not None:
            session = conn.execute("SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            if session is None:
                return []
            if session["user_id"] != user_id:
                raise PermissionError(f"User {user_id} không có quyền truy cập tin nhắn của phiên {session_id}")
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC, seq ASC",
            (session_id,),
        ).fetchall()
    return [_message_row(r) for r in rows]


# ───────────────────────────────────────────────────────────────────────────────
# Auth tokens (Bước 3). Module này chỉ lưu/đọc; việc sinh token, băm, kiểm hạn ở auth_service.
# ───────────────────────────────────────────────────────────────────────────────
def save_auth_token(token_hash: str, user_id: str, expires_at: str) -> None:
    """Lưu một token (đã băm). `expires_at` là chuỗi ISO 8601 UTC. user_id lạ -> UserNotFoundError."""
    if not token_hash or not expires_at:
        raise ValueError("token_hash và expires_at không được để trống")
    with closing(_connect()) as conn:
        try:
            with conn:
                conn.execute(
                    "INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (token_hash, user_id, _now(), expires_at),
                )
        except sqlite3.IntegrityError as exc:
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise UserNotFoundError(f"không có user: {user_id}") from exc
            raise  # lỗi khác (vd. trùng token_hash): không che giấu


def get_auth_token(token_hash: str) -> Optional[dict]:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM auth_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
    if row is None:
        return None
    return {k: row[k] for k in ("token_hash", "user_id", "created_at", "expires_at")}


def delete_auth_token(token_hash: str) -> bool:
    """Xóa token. Trả True nếu có xóa, False nếu token không tồn tại (idempotent)."""
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
    return cur.rowcount > 0


def delete_expired_auth_tokens(now_iso: str) -> int:
    """Dọn token có expires_at < now_iso (so sánh chuỗi; cả hai phải cùng định dạng ISO UTC). Trả số dòng xóa."""
    with closing(_connect()) as conn:
        with conn:
            cur = conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now_iso,))
    return cur.rowcount


__all__ = [
    "DEFAULT_DB_PATH", "DB_PATH_ENV", "ACTIVE_STATUSES", "VALID_STATUSES", "VALID_ROLES",
    "DuplicateEmailError", "UserNotFoundError", "SessionNotFoundError", "StaleSessionError",
    "get_db_path", "init_db", "default_trip_request",
    "create_user", "get_user_by_email", "get_user_by_id",
    "get_or_create_active_session", "get_session_by_id", "get_session_for_user",
    "update_session_trip_request", "commit_turn",
    "add_chat_message", "get_session_messages",
    "save_auth_token", "get_auth_token", "delete_auth_token", "delete_expired_auth_tokens",
]
