"""
app/services/auth_service.py
===============================================================================
Lát 3 - Bước 3: Dịch vụ xác thực và dependency bảo mật. PRODUCT_SPEC Mục 3.1, 3.2.

Thiết kế (zero-dependency ngoài FastAPI/Pydantic đã có):
- Mật khẩu: PBKDF2-HMAC-SHA256, salt ngẫu nhiên 16 byte, định dạng tự mô tả
  `pbkdf2_sha256$<vòng lặp>$<salt b64>$<hash b64>`. Verify đọc số vòng lặp TỪ CHUỖI HASH, nên đổi
  PASSWORD_HASH_ITERATIONS sau này không làm hỏng mật khẩu cũ. So sánh bằng hmac.compare_digest.
- Token đăng nhập: chuỗi ngẫu nhiên không đoán được (secrets.token_urlsafe(32)), opaque. DB chỉ lưu
  SHA-256 của token (bảng auth_tokens), nên: thu hồi được thật (logout), sống qua restart/nhiều worker,
  không cần khóa bí mật phải quản lý, lộ file DB không lộ token dùng được.
- Đọc token: header `Authorization: Bearer <token>` (ưu tiên) hoặc cookie `access_token`.
- Mọi lỗi xác thực trả 401 với thông điệp chung (không tiết lộ email có tồn tại hay không).

Cấu hình (biến môi trường, đọc ở mỗi lần gọi):
- PASSWORD_HASH_ITERATIONS  mặc định 600000 (khuyến nghị OWASP cho PBKDF2-SHA256)
- AUTH_TOKEN_TTL_SECONDS    mặc định 2592000 (30 ngày; Mục 3.2: "thời hạn dài")

Module này KHÔNG set cookie; route (Bước sau) tự set cookie `httpOnly` bằng COOKIE_NAME nếu chọn cookie.
"""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, Request

from app.chat_models import TokenResponse, UserOut, UserRegisterRequest
from app.services import chat_storage

COOKIE_NAME = "access_token"
HASH_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
MAX_ITERATIONS = 10_000_000  # chặn hash bị sửa với số vòng lặp khổng lồ (DoS khi verify)
DEFAULT_TOKEN_TTL_SECONDS = 30 * 24 * 3600
SALT_BYTES = 16

INVALID_CREDENTIALS_DETAIL = "email hoặc mật khẩu không đúng"  # Mục 3.2: báo chung
NOT_AUTHENTICATED_DETAIL = "chưa đăng nhập"
INVALID_TOKEN_DETAIL = "phiên đăng nhập không hợp lệ hoặc đã hết hạn"
DUPLICATE_EMAIL_DETAIL = "email đã được đăng ký"


# ───────────────────────────────────────────────────────────────────────────────
# Cấu hình & tiện ích
# ───────────────────────────────────────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} phải là số nguyên, nhận {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} phải > 0")
    return value


def _iterations() -> int:
    return _env_int("PASSWORD_HASH_ITERATIONS", DEFAULT_ITERATIONS)


def _token_ttl() -> timedelta:
    return timedelta(seconds=_env_int("AUTH_TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL_SECONDS))


def _utcnow() -> datetime:
    """Tách riêng để test có thể giả lập thời gian."""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    # timespec cố định => các chuỗi ISO so sánh theo thứ tự chữ cái đúng thứ tự thời gian.
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


# ───────────────────────────────────────────────────────────────────────────────
# Mật khẩu
# ───────────────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Băm mật khẩu với salt ngẫu nhiên mới. Mỗi lần gọi cho kết quả khác nhau."""
    if not isinstance(password, str) or not password:
        raise ValueError("mật khẩu phải là chuỗi không rỗng")
    iterations = _iterations()
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (HASH_ALGORITHM, str(iterations), base64.b64encode(salt).decode("ascii"),
         base64.b64encode(digest).decode("ascii"))
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """True nếu khớp. Hash hỏng/lạ định dạng, hoặc đầu vào sai kiểu -> False (không ném lỗi)."""
    try:
        algorithm, iter_text, salt_b64, digest_b64 = stored_hash.split("$")
        if algorithm != HASH_ALGORITHM:
            return False
        iterations = int(iter_text)
        if not 1 <= iterations <= MAX_ITERATIONS:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
    except (ValueError, TypeError, AttributeError):  # binascii.Error, UnicodeEncodeError là ValueError
        return False
    return hmac.compare_digest(candidate, expected)


@lru_cache(maxsize=8)
def _dummy_hash(iterations: int) -> str:
    """Hash giả để vẫn tốn thời gian băm khi email không tồn tại (giảm lộ email qua độ trễ)."""
    salt = b"\x00" * SALT_BYTES
    digest = hashlib.pbkdf2_hmac("sha256", b"dummy-password", salt, iterations)
    return "$".join((HASH_ALGORITHM, str(iterations), base64.b64encode(salt).decode("ascii"),
                     base64.b64encode(digest).decode("ascii")))


# ───────────────────────────────────────────────────────────────────────────────
# Token
# ───────────────────────────────────────────────────────────────────────────────
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user_id: str) -> str:
    """Sinh token mới cho user, lưu băm + hạn dùng. Trả token GỐC (chỉ có lúc này, không lấy lại được)."""
    now = _utcnow()
    chat_storage.delete_expired_auth_tokens(_iso(now))  # dọn dần, rẻ nhờ index
    token = secrets.token_urlsafe(32)
    chat_storage.save_auth_token(_hash_token(token), user_id, _iso(now + _token_ttl()))
    return token


def revoke_token(token: Optional[str]) -> None:
    """Thu hồi token (logout). Idempotent: token rỗng/không tồn tại/đã thu hồi đều không lỗi."""
    if not token or not isinstance(token, str):
        return
    chat_storage.delete_auth_token(_hash_token(token))


def get_user_from_token(token: Optional[str]) -> UserOut:
    """Token hợp lệ -> UserOut; ngược lại HTTPException 401. Token hết hạn bị xóa khỏi DB."""
    if not token or not isinstance(token, str):
        raise _unauthorized(NOT_AUTHENTICATED_DETAIL)
    token_hash = _hash_token(token)
    record = chat_storage.get_auth_token(token_hash)
    if record is None:
        raise _unauthorized(INVALID_TOKEN_DETAIL)
    if datetime.fromisoformat(record["expires_at"]) <= _utcnow():
        chat_storage.delete_auth_token(token_hash)
        raise _unauthorized(INVALID_TOKEN_DETAIL)
    user = chat_storage.get_user_by_id(record["user_id"])
    if user is None:  # user đã bị xóa
        chat_storage.delete_auth_token(token_hash)
        raise _unauthorized(INVALID_TOKEN_DETAIL)
    return _to_user_out(user)


def _to_user_out(user: dict) -> UserOut:
    # Chọn trường tường minh: password_hash không bao giờ đi vào model trả ra.
    return UserOut(id=user["id"], email=user["email"], created_at=user["created_at"])


# ───────────────────────────────────────────────────────────────────────────────
# Nghiệp vụ
# ───────────────────────────────────────────────────────────────────────────────
def register_user(email: str, password: str) -> UserOut:
    """Đăng ký. Kiểm định dạng email/độ dài mật khẩu bằng UserRegisterRequest (sai -> ValidationError,
    là ValueError; route thường đã chặn trước bằng chính schema đó). Trùng email -> HTTPException 409."""
    data = UserRegisterRequest(email=email, password=password)
    try:
        user = chat_storage.create_user(data.email, hash_password(data.password))
    except chat_storage.DuplicateEmailError:
        raise HTTPException(status_code=409, detail=DUPLICATE_EMAIL_DETAIL)
    return _to_user_out(user)


def authenticate_user(email: str, password: str) -> TokenResponse:
    """Đăng nhập. Sai email hoặc sai mật khẩu -> HTTPException 401 cùng một thông điệp chung."""
    user = chat_storage.get_user_by_email(email) if isinstance(email, str) else None
    stored = user["password_hash"] if user else _dummy_hash(_iterations())
    password_ok = verify_password(password, stored)  # luôn băm một lần dù email có tồn tại hay không
    if user is None or not password_ok:
        raise _unauthorized(INVALID_CREDENTIALS_DETAIL)
    return TokenResponse(access_token=issue_token(user["id"]), user=_to_user_out(user))


def register_and_login(email: str, password: str) -> TokenResponse:
    """Mục 3.2: đăng ký xong đăng nhập luôn (không xác minh email)."""
    user = register_user(email, password)
    return TokenResponse(access_token=issue_token(user.id), user=user)


# ───────────────────────────────────────────────────────────────────────────────
# FastAPI dependency
# ───────────────────────────────────────────────────────────────────────────────
def extract_token(authorization: Optional[str], cookie_token: Optional[str] = None) -> Optional[str]:
    """Header `Authorization: Bearer <token>` được ưu tiên; không có (hoặc không phải Bearer) thì dùng cookie."""
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    return cookie_token.strip() if cookie_token and cookie_token.strip() else None


def get_current_user(request: Request) -> UserOut:
    """Dependency cho MỌI route chat: `user: UserOut = Depends(get_current_user)`.
    Thiếu token, token sai/hết hạn/đã thu hồi -> HTTPException 401 (Mục 3.1: chặn ở backend)."""
    token = extract_token(request.headers.get("authorization"), request.cookies.get(COOKIE_NAME))
    return get_user_from_token(token)


__all__ = [
    "COOKIE_NAME", "hash_password", "verify_password", "issue_token", "revoke_token",
    "get_user_from_token", "register_user", "authenticate_user", "register_and_login",
    "extract_token", "get_current_user",
]
