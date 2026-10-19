"""
app/services/chat_storage.py
===============================================================================
Lát 3 - Tầng lưu trữ SQLite riêng (`chat_state.db`). PRODUCT_SPEC Mục 8.1.

Bản này sửa các lỗi review Bước 1 (mã trong ngoặc là mã phát hiện của review):
- (N1/N2) Migration có phiên bản (`PRAGMA user_version`), chạy NGUYÊN TỬ trong một `BEGIN IMMEDIATE`:
  DB mới, DB Bước 2 (chưa có `version`/`seq`), DB Bước 1 dở dang đều được đưa về schema hiện tại; lỗi giữa
  chừng thì rollback toàn bộ, không để lại schema nửa vời.
- (A1/A2) `commit_turn`: CAS theo `version` + ghi phiên và tin nhắn trong MỘT transaction. Có kiểm tra
  chuyển trạng thái hợp lệ (ALLOWED_TRANSITIONS). `transition_session_status` là đường ghi DUY NHẤT dành cho
  planner/worker (CAS theo status, không bao giờ ghi đè kết quả của bên khác).
- (A5) Cột `status` là nguồn sự thật; trường `status` trong JSON `trip_request` chỉ là bản sao, được ép
  khớp khi ghi và khi đọc.
- (A6) Thứ tự tin nhắn CHỈ theo `seq` (AUTOINCREMENT), không phụ thuộc đồng hồ.
- (C1) Truy cập theo user là bắt buộc: `get_session_for_user`, `get_session_messages(session_id, user_id)`.
  Các hàm không lọc user được đặt tên rõ (`get_session_by_id`, `list_messages_unscoped`) và CHỈ dành cho
  nội bộ/test, router không được gọi.
- (N4) JSON `trip_request` hỏng KHÔNG làm ném lỗi khi đọc: trả `trip_request=None, corrupt=True`.
  `quarantine_session` chuyển phiên hỏng sang 'error' mà không sửa/xoá dữ liệu gốc.
- (N6) `update_session_trip_request` trả đúng version mới; mọi thao tác ghi dùng `BEGIN IMMEDIATE`.

Quy ước:
- File DB: biến môi trường `CHAT_DB_PATH` (mặc định `./chat_state.db`), đọc ở MỖI lần kết nối.
- Mỗi lệnh gọi mở một kết nối riêng (an toàn với thread của FastAPI); `isolation_level=None`, mọi
  transaction ghi đều tường minh qua `_write_txn`.
- `trip_request`/`payload` lưu TEXT JSON, khi đọc luôn giải mã. Thời gian: ISO 8601 UTC. id: uuid4.
- Module này CHỈ lo lưu/đọc: không băm mật khẩu, không gọi NLU, không import dialogue_models.
"""
import json
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

DEFAULT_DB_PATH = "./chat_state.db"
DB_PATH_ENV = "CHAT_DB_PATH"
DB_TIMEOUT_SECONDS = 10.0  # chờ khoá ghi tối đa; hết hạn -> sqlite3.OperationalError (router đổi thành 503)
SCHEMA_VERSION = 2

ACTIVE_STATUSES = ("collecting", "ready")  # "đang dở": mỗi user tối đa MỘT phiên (Mục 8.1)
VALID_STATUSES = ("collecting", "ready", "planning", "planned", "error")  # Mục 4.4
VALID_ROLES = ("user", "assistant")

# Máy trạng thái áp dụng cho commit_turn / transition_session_status.
# planning -> ready: bù trừ khi planner không khởi động được. planning -> planning: gắn lại plan_task_id.
ALLOWED_TRANSITIONS: Dict[str, frozenset] = {
    "collecting": frozenset({"collecting", "ready", "planning", "error"}),
    "ready": frozenset({"collecting", "ready", "planning", "error"}),
    "planning": frozenset({"planning", "planned", "ready", "error"}),
    "planned": frozenset(),
    "error": frozenset(),
}



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
    """Phiên đã bị thay đổi bởi luồng/tiến trình khác (CAS `version` không khớp)."""


class InvalidTransitionError(ValueError):
    """Chuyển trạng thái không nằm trong ALLOWED_TRANSITIONS."""


# ───────────────────────────────────────────────────────────────────────────────
# Schema & migration
# ───────────────────────────────────────────────────────────────────────────────
_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id           TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL REFERENCES users(id),
        status       TEXT NOT NULL,
        trip_request TEXT NOT NULL,
        version      INTEGER NOT NULL DEFAULT 1,
        updated_at   TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        seq        INTEGER PRIMARY KEY AUTOINCREMENT,
        id         TEXT UNIQUE NOT NULL,
        session_id TEXT NOT NULL REFERENCES chat_sessions(id),
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        payload    TEXT,
        created_at TEXT NOT NULL
    )""",
    """
    CREATE TABLE IF NOT EXISTS auth_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users(id),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
)

_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id)",
    # Ép ở mức DB: mỗi user tối đa MỘT phiên đang dở (chống race khi 2 request đồng thời).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_one_active_per_user "
    "ON chat_sessions(user_id) WHERE status IN ('collecting', 'ready')",
    "CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq ON chat_messages(session_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at)",
)


def get_db_path() -> str:
    path = os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH
    if path == ":memory:":
        # Mỗi lệnh gọi mở kết nối mới => ":memory:" sẽ là DB trống mỗi lần. Báo lỗi rõ thay vì lỗi ngầm.
        raise ValueError("CHAT_DB_PATH=':memory:' không được hỗ trợ; dùng đường dẫn file (vd. tmp_path).")
    return path


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Đưa DB về schema hiện tại. Idempotent, gọi TRONG một transaction đang mở (DDL của SQLite có tính giao dịch)."""
    # 1) chat_messages kiểu cũ (không có `seq`) -> đổi tên để dựng lại, giữ thứ tự cũ (created_at, rowid).
    legacy_messages = False
    if _table_exists(conn, "chat_messages") and "seq" not in _table_columns(conn, "chat_messages"):
        conn.execute("ALTER TABLE chat_messages RENAME TO chat_messages_legacy")
        legacy_messages = True

    # 2) tạo bảng còn thiếu (kể cả khi init lần trước dở dang)
    for statement in _TABLE_STATEMENTS:
        conn.execute(statement)

    # 3) chat_sessions kiểu cũ thiếu `version`
    if "version" not in _table_columns(conn, "chat_sessions"):
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

    # 4) chuyển dữ liệu tin nhắn cũ sang bảng mới (seq cấp theo thứ tự chèn)
    if legacy_messages:
        conn.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, payload, created_at) "
            "SELECT id, session_id, role, content, payload, created_at FROM chat_messages_legacy "
            "ORDER BY created_at ASC, rowid ASC"
        )
        conn.execute("DROP TABLE chat_messages_legacy")  # kéo theo các index cũ của nó

    # 5) index (sau khi cột đã tồn tại). Index theo created_at của bản cũ không còn dùng.
    conn.execute("DROP INDEX IF EXISTS idx_chat_messages_session")
    for statement in _INDEX_STATEMENTS:
        conn.execute(statement)


def _migrate(conn: sqlite3.Connection) -> None:
    try:
        mode = str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower()
        if mode != "wal":
            conn.execute("PRAGMA journal_mode=WAL;")  # phải đặt NGOÀI transaction
    except sqlite3.OperationalError:
        pass  # Luồng khác đang giữ khóa độc quyền sẽ hoàn tất bật WAL
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]  # đọc lại trong khoá: có thể bên khác vừa migrate xong
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"DB có schema v{current} mới hơn code (v{SCHEMA_VERSION}); từ chối chạy để tránh làm hỏng dữ liệu."
            )
        if current != SCHEMA_VERSION:
            _apply_schema(conn)
            conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise


def _connect() -> sqlite3.Connection:
    path = get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=DB_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            _migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def init_db() -> None:
    """Tạo/migrate DB (nên gọi lúc khởi động ứng dụng; các hàm khác cũng tự gọi)."""
    with closing(_connect()):
        pass


@contextmanager
def _write_txn(conn: sqlite3.Connection):
    """Transaction ghi tường minh: BEGIN IMMEDIATE (lấy khoá ghi ngay, không bị SQLITE_BUSY_SNAPSHOT khi nâng cấp
    từ đọc sang ghi). Lỗi bất kỳ -> rollback toàn bộ rồi ném lại."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    else:
        conn.commit()


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


def _parse_trip(trip_request_json: Union[str, Mapping[str, Any]]) -> dict:
    if isinstance(trip_request_json, str):
        try:
            parsed = json.loads(trip_request_json)
        except json.JSONDecodeError as exc:
            raise ValueError("trip_request_json không phải JSON hợp lệ") from exc
    else:
        parsed = dict(trip_request_json)
    if not isinstance(parsed, dict):
        raise ValueError("trip_request phải là một JSON object")
    return parsed


def _user_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row["password_hash"],
        "created_at": row["created_at"],
    }


def _session_row(row: sqlite3.Row) -> dict:
    """JSON hỏng KHÔNG ném lỗi: trả trip_request=None, corrupt=True để tầng trên cách ly phiên (N4).
    Cột `status` là nguồn sự thật: trường status trong JSON luôn được ép khớp (A5)."""
    corrupt = False
    try:
        trip = json.loads(row["trip_request"])
        if not isinstance(trip, dict):
            raise ValueError("trip_request không phải object")
    except (TypeError, ValueError):
        trip, corrupt = None, True
    else:
        if "status" in trip:
            trip["status"] = row["status"]
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "trip_request": trip,
        "version": row["version"],
        "updated_at": row["updated_at"],
        "corrupt": corrupt,
    }


def _message_row(row: sqlite3.Row) -> dict:
    payload = row["payload"]
    try:
        decoded = None if payload is None else json.loads(payload)
    except ValueError:
        decoded = None  # payload hỏng chỉ làm mất chip, không làm hỏng cả lịch sử
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "payload": decoded,
        "created_at": row["created_at"],
        "seq": row["seq"],
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
            with _write_txn(conn):
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
    # Unique index một phần bảo đảm tối đa 1 dòng; ORDER BY chỉ để xác định khi dữ liệu cũ vi phạm.
    return conn.execute(
        f"SELECT * FROM chat_sessions WHERE user_id = ? AND status IN ({placeholders}) "
        "ORDER BY updated_at DESC LIMIT 1",
        (user_id, *ACTIVE_STATUSES),
    ).fetchone()


def get_or_create_active_session(user_id: str) -> dict:
    """Trả phiên đang dở ('collecting' / 'ready') của user; chưa có thì tạo phiên 'collecting' mới (version=1).
    Kiểm tra + tạo nằm trong MỘT transaction ghi nên không có race giữa hai request. user_id lạ -> UserNotFoundError."""
    with closing(_connect()) as conn:
        row = _select_active_session(conn, user_id)  # đường nhanh, không cần khoá ghi
        if row:
            return _session_row(row)
        with _write_txn(conn):
            row = _select_active_session(conn, user_id)
            if row:
                return _session_row(row)
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise UserNotFoundError(f"không có user: {user_id}")
            session_id = _new_id()
            conn.execute(
                "INSERT INTO chat_sessions (id, user_id, status, trip_request, version, updated_at) "
                "VALUES (?, ?, 'collecting', ?, 1, ?)",
                (session_id, user_id, _dumps(default_trip_request(session_id)), _now()),
            )
            row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        return _session_row(row)


def get_session_for_user(session_id: str, user_id: str) -> Optional[dict]:
    """Phiên của user, hoặc None nếu không tồn tại HOẶC thuộc user khác (không phân biệt ở tầng này)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
        ).fetchone()
    return _session_row(row) if row else None


def get_session_owner(session_id: str) -> Optional[str]:
    """Chỉ trả user_id chủ phiên (None nếu không có phiên) để router phân biệt 404/403. Không lộ dữ liệu phiên.
    Nếu muốn che sự tồn tại của phiên người khác: router bỏ lời gọi này và trả 404 cho mọi trường hợp None."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT user_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return row["user_id"] if row else None


def get_session_by_id(session_id: str) -> Optional[dict]:
    """KHÔNG LỌC USER - chỉ dành cho nội bộ/test/worker. Router phải dùng get_session_for_user."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_row(row) if row else None


def update_session_trip_request(
    session_id: str,
    trip_request_json: Union[str, Mapping[str, Any]],
    status: str,
    expected_version: Optional[int] = None,
    user_id: Optional[str] = None,
) -> int:
    """Ghi đè bản yêu cầu + status; trả version MỚI.
    - Có `expected_version`: CAS, BẮT BUỘC kèm `user_id`; lệch version -> StaleSessionError, sai chủ -> PermissionError.
    - Không có `expected_version`: ghi đè vô điều kiện, KHÔNG kiểm tra chuyển trạng thái (hàm quản trị/test;
      luồng chat phải dùng commit_turn, worker dùng transition_session_status).
    Trường `status` trong JSON luôn bị ép bằng `status` (A5)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"status không hợp lệ: {status!r}")
    parsed = _parse_trip(trip_request_json)
    if expected_version is not None and user_id is None:
        raise ValueError("user_id là bắt buộc khi dùng expected_version (CAS luôn phải kèm phân quyền)")
    if "status" in parsed:
        parsed["status"] = status
    now = _now()
    with closing(_connect()) as conn:
        with _write_txn(conn):
            sql = "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? WHERE id = ?"
            params: List[Any] = [status, _dumps(parsed), now, session_id]
            if user_id is not None:
                sql += " AND user_id = ?"
                params.append(user_id)
            if expected_version is not None:
                sql += " AND version = ?"
                params.append(expected_version)
            cur = conn.execute(sql, tuple(params))
            if cur.rowcount == 0:
                sess = conn.execute("SELECT user_id, version FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
                if sess is None:
                    raise SessionNotFoundError(f"không có phiên: {session_id}")
                if user_id is not None and sess["user_id"] != user_id:
                    raise PermissionError(f"user {user_id} không sở hữu phiên {session_id}")
                raise StaleSessionError(
                    f"Phiên {session_id} đã thay đổi: version hiện tại={sess['version']}, mong đợi={expected_version}"
                )
            return conn.execute("SELECT version FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()["version"]


def commit_turn(
    session_id: str,
    user_id: str,
    expected_version: int,
    new_status: str,
    trip_request_json: Union[str, Mapping[str, Any]],
    messages: List[Mapping[str, Any]],
) -> Tuple[dict, List[dict]]:
    """Ghi NGUYÊN TỬ một lượt (đổi trạng thái + tin nhắn) trong một `BEGIN IMMEDIATE`.

    Thứ tự kiểm tra: phiên tồn tại (SessionNotFoundError) -> đúng chủ (PermissionError) -> version khớp
    (StaleSessionError) -> chuyển trạng thái hợp lệ (InvalidTransitionError). Lỗi bất kỳ, kể cả khi chèn tin nhắn,
    rollback toàn bộ. Trả (phiên mới - đọc TRONG transaction, danh sách tin nhắn đã tạo).
    `messages` rỗng là hợp lệ (vd. chỉ đổi trạng thái/gắn lại plan_task_id)."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"status không hợp lệ: {new_status!r}")
    parsed_trip = _parse_trip(trip_request_json)
    for msg in messages:
        if msg.get("role") not in VALID_ROLES:
            raise ValueError(f"role không hợp lệ: {msg.get('role')!r}")
        if not isinstance(msg.get("content"), str):
            raise ValueError("content phải là chuỗi")
    if "status" in parsed_trip:
        parsed_trip["status"] = new_status  # A5: bản sao trong JSON luôn khớp cột

    now = _now()
    with closing(_connect()) as conn:
        with _write_txn(conn):
            sess = conn.execute(
                "SELECT id, user_id, status, version FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if sess is None:
                raise SessionNotFoundError(f"không có phiên: {session_id}")
            if sess["user_id"] != user_id:
                raise PermissionError(f"user {user_id} không có quyền truy cập phiên {session_id}")
            if sess["version"] != expected_version:
                raise StaleSessionError(
                    f"Phiên {session_id} đã thay đổi: version hiện tại={sess['version']}, mong đợi={expected_version}"
                )
            if new_status not in ALLOWED_TRANSITIONS[sess["status"]]:
                raise InvalidTransitionError(f"không được chuyển {sess['status']!r} -> {new_status!r}")

            cur = conn.execute(
                "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? "
                "WHERE id = ? AND user_id = ? AND version = ?",
                (new_status, _dumps(parsed_trip), now, session_id, user_id, expected_version),
            )
            if cur.rowcount != 1:  # không thể xảy ra trong BEGIN IMMEDIATE; giữ làm chốt an toàn
                raise StaleSessionError(f"CAS thất bại trên phiên {session_id}")

            created: List[dict] = []
            for msg in messages:
                msg_id = msg.get("id") or _new_id()
                payload = msg.get("payload")
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (msg_id, session_id, msg["role"], msg["content"], None if payload is None else _dumps(payload), now),
                )
                created.append({
                    "id": msg_id, "session_id": session_id, "role": msg["role"], "content": msg["content"],
                    "payload": payload, "created_at": now,
                })
            updated = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        return _session_row(updated), created


def transition_session_status(session_id: str, from_status: str, to_status: str) -> bool:
    """Đường ghi DUY NHẤT dành cho planner/worker: CAS theo status (không biết version, không biết user).
    Trả True nếu chuyển thành công, False nếu phiên không còn ở `from_status` (bên khác đã đổi: KHÔNG ghi đè).
    Phiên không tồn tại -> SessionNotFoundError. Chuyển trái luật -> InvalidTransitionError."""
    if from_status not in VALID_STATUSES or to_status not in VALID_STATUSES:
        raise ValueError(f"status không hợp lệ: {from_status!r} -> {to_status!r}")
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise InvalidTransitionError(f"không được chuyển {from_status!r} -> {to_status!r}")
    with closing(_connect()) as conn:
        with _write_txn(conn):
            row = conn.execute("SELECT status, trip_request FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise SessionNotFoundError(f"không có phiên: {session_id}")
            if row["status"] != from_status:
                return False
            trip_text = row["trip_request"]
            try:
                trip = json.loads(trip_text)
                if isinstance(trip, dict) and "status" in trip:
                    trip["status"] = to_status
                    trip_text = _dumps(trip)
            except ValueError:
                pass  # JSON hỏng: giữ nguyên để điều tra; cột status vẫn là nguồn sự thật
            cur = conn.execute(
                "UPDATE chat_sessions SET status = ?, trip_request = ?, version = version + 1, updated_at = ? "
                "WHERE id = ? AND status = ?",
                (to_status, trip_text, _now(), session_id, from_status),
            )
            return cur.rowcount == 1


def quarantine_session(session_id: str, user_id: str) -> bool:
    """Cách ly phiên đang dở bị hỏng: chuyển sang 'error' để user mở được phiên mới. KHÔNG sửa/xoá trip_request
    (giữ nguyên để điều tra/khôi phục). Trả True nếu có đổi trạng thái."""
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with closing(_connect()) as conn:
        with _write_txn(conn):
            cur = conn.execute(
                "UPDATE chat_sessions SET status = 'error', version = version + 1, updated_at = ? "
                f"WHERE id = ? AND user_id = ? AND status IN ({placeholders})",
                (_now(), session_id, user_id, *ACTIVE_STATUSES),
            )
            return cur.rowcount == 1


# ───────────────────────────────────────────────────────────────────────────────
# Messages
# ───────────────────────────────────────────────────────────────────────────────
def add_chat_message(session_id: str, role: str, content: str, payload: Optional[Any] = None) -> dict:
    """Thêm tin nhắn đơn lẻ (role 'user'|'assistant'). Luồng chat dùng commit_turn; hàm này dành cho nội bộ/test.
    Phiên không tồn tại -> SessionNotFoundError. Không đổi `version` (chỉ cập nhật updated_at)."""
    if role not in VALID_ROLES:
        raise ValueError(f"role không hợp lệ: {role!r}")
    if not isinstance(content, str):
        raise ValueError("content phải là chuỗi")
    message_id, created_at = _new_id(), _now()
    payload_text = None if payload is None else _dumps(payload)
    with closing(_connect()) as conn:
        try:
            with _write_txn(conn):
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


def get_session_messages(session_id: str, user_id: str) -> List[dict]:
    """Tin nhắn của phiên THUỘC user_id, tăng dần theo `seq`. Phiên không tồn tại hoặc của người khác -> [].
    Một truy vấn JOIN duy nhất (không có khe hở giữa kiểm tra quyền và đọc)."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT m.* FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
            "WHERE m.session_id = ? AND s.user_id = ? ORDER BY m.seq ASC",
            (session_id, user_id),
        ).fetchall()
    return [_message_row(r) for r in rows]


def list_messages_unscoped(session_id: str) -> List[dict]:
    """KHÔNG LỌC USER - chỉ dành cho nội bộ/test. Router phải dùng get_session_messages."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY seq ASC", (session_id,)
        ).fetchall()
    return [_message_row(r) for r in rows]


# ───────────────────────────────────────────────────────────────────────────────
# Auth tokens. Module này chỉ lưu/đọc; việc sinh token, băm, kiểm hạn ở auth_service.
# ───────────────────────────────────────────────────────────────────────────────
def save_auth_token(token_hash: str, user_id: str, expires_at: str) -> None:
    """Lưu một token (đã băm). `expires_at` là chuỗi ISO 8601 UTC. user_id lạ -> UserNotFoundError."""
    if not token_hash or not expires_at:
        raise ValueError("token_hash và expires_at không được để trống")
    with closing(_connect()) as conn:
        try:
            with _write_txn(conn):
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
        with _write_txn(conn):
            cur = conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))
        return cur.rowcount > 0


def delete_expired_auth_tokens(now_iso: str) -> int:
    """Dọn token có expires_at < now_iso (so sánh chuỗi; cả hai phải cùng định dạng ISO UTC). Trả số dòng xóa."""
    with closing(_connect()) as conn:
        with _write_txn(conn):
            cur = conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (now_iso,))
        return cur.rowcount


__all__ = [
    "DEFAULT_DB_PATH", "DB_PATH_ENV", "DB_TIMEOUT_SECONDS", "SCHEMA_VERSION",
    "ACTIVE_STATUSES", "VALID_STATUSES", "VALID_ROLES", "ALLOWED_TRANSITIONS",
    "DuplicateEmailError", "UserNotFoundError", "SessionNotFoundError", "StaleSessionError",
    "InvalidTransitionError",
    "get_db_path", "init_db", "default_trip_request",
    "create_user", "get_user_by_email", "get_user_by_id",
    "get_or_create_active_session", "get_session_for_user", "get_session_owner", "get_session_by_id",
    "update_session_trip_request", "commit_turn", "transition_session_status", "quarantine_session",
    "add_chat_message", "get_session_messages", "list_messages_unscoped",
    "save_auth_token", "get_auth_token", "delete_auth_token", "delete_expired_auth_tokens",
]
