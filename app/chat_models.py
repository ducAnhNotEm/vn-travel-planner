"""
app/chat_models.py
===============================================================================
Lát 3 - Bước 1: Khế ước dữ liệu (Pydantic v2) cho Xác thực và Phiên chat. PRODUCT_SPEC Mục 3.2, 7.2, 8.

Đây là HỢP ĐỒNG API (vào/ra của route), tách khỏi mô hình miền hội thoại ở app/dialogue_models.py
(TripRequest, ChipItem, ClarificationTurn...). File này chỉ IMPORT từ dialogue_models, không sửa nó.

Nguyên tắc:
- Schema ĐẦU VÀO (request) dùng extra="forbid": không nhận trường lạ (chống mass-assignment như
  {"role": "admin"}; Mục 3.2 chốt "không phân quyền").
- Schema ĐẦU RA (response) mặc định bỏ qua trường lạ, nên một dòng DB có `password_hash` đưa vào
  UserOut cũng KHÔNG bao giờ lọt ra JSON.
- Không phụ thuộc `email-validator`: email kiểm bằng regex (+ chuẩn hóa chữ thường, Mục 3.2).
- Hằng số giới hạn gom ở đầu file để chốt/ sửa một chỗ.
"""
import re
from datetime import datetime
from typing import Annotated, List, Literal, Optional, Union
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.dialogue_models import ChipItem, TripRequest

# ───────────────────────────────────────────────────────────────────────────────
# Hằng số
# ───────────────────────────────────────────────────────────────────────────────
# LƯU Ý: Mục 3.2 của spec ghi "mật khẩu từ 8 ký tự"; yêu cầu Bước 1 ghi 6. Đang theo SPEC (8).
# Muốn đổi, sửa DUY NHẤT hằng số này (test dùng chính hằng số, không hard-code).
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128   # chặn payload khổng lồ khi băm; lớp băm (bcrypt) còn giới hạn riêng 72 byte
MAX_EMAIL_LENGTH = 254      # giới hạn RFC 5321
MAX_MESSAGE_CHARS = 2000    # spec chưa nêu; chặn tin nhắn quá dài đẩy vào NLU

SessionStatus = Literal["collecting", "ready", "planning", "planned", "error"]  # khớp TripRequest.status
MessageRole = Literal["user", "assistant"]


# ───────────────────────────────────────────────────────────────────────────────
# Bộ chuẩn hóa dùng chung
# ───────────────────────────────────────────────────────────────────────────────
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_EMAIL_RE = re.compile(
    rf"^{_ATOM}(?:\.{_ATOM})*"              # phần local: các đoạn cách nhau MỘT dấu chấm (không đầu/cuối/đôi)
    rf"@(?:{_LABEL}\.)+"                    # miền: có ít nhất một dấu chấm
    rf"(?:[A-Za-z]{{2,}}|xn--[A-Za-z0-9-]{{1,59}})$"  # đuôi miền: chữ cái hoặc punycode
)


def normalize_email(value: str) -> str:
    """Cắt khoảng trắng, đổi chữ thường, kiểm định dạng. Sai -> ValueError."""
    email = value.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(email):
        raise ValueError("email không đúng định dạng")
    return email


def _normalize_login_email(value: str) -> str:
    """Đăng nhập: KHÔNG kiểm định dạng (sai gì cũng trả chung 'email hoặc mật khẩu không đúng', Mục 3.2)."""
    email = value.strip().lower()
    if not email:
        raise ValueError("email không được để trống")
    return email


def _coerce_id(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value  # kiểu khác để bước kiểm tra `str` từ chối


def _coerce_iso(value):
    """Nhận datetime hoặc chuỗi ISO 8601; luôn trả chuỗi ISO."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        probe = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
        try:
            datetime.fromisoformat(probe)
        except ValueError:
            raise ValueError("created_at phải là chuỗi ISO 8601")
        return text
    return value


IdStr = Annotated[str, BeforeValidator(_coerce_id), Field(min_length=1)]
IsoDateTimeStr = Annotated[str, BeforeValidator(_coerce_iso)]
RegisterEmail = Annotated[str, AfterValidator(normalize_email)]
LoginEmail = Annotated[str, AfterValidator(_normalize_login_email)]


# ───────────────────────────────────────────────────────────────────────────────
# 1. Xác thực
# ───────────────────────────────────────────────────────────────────────────────
class UserRegisterRequest(BaseModel):
    """POST /api/auth/register. Email lưu chữ thường; mật khẩu giữ NGUYÊN VĂN (không strip) để băm."""
    model_config = ConfigDict(extra="forbid")

    email: RegisterEmail
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class UserLoginRequest(BaseModel):
    """POST /api/auth/login. Không kiểm độ dài/định dạng: sai thì lớp xác thực báo chung 401."""
    model_config = ConfigDict(extra="forbid")

    email: LoginEmail
    password: str = Field(..., min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    """Thông tin user trả ra. Không có password_hash (trường lạ bị bỏ qua)."""
    id: IdStr
    email: str
    created_at: IsoDateTimeStr


class TokenResponse(BaseModel):
    access_token: str = Field(..., min_length=1)
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


# ───────────────────────────────────────────────────────────────────────────────
# 2. Phiên chat & tin nhắn
# ───────────────────────────────────────────────────────────────────────────────
def _require_same_status(status: str, trip_request: TripRequest) -> None:
    if status != trip_request.status:
        raise ValueError(f"status ({status!r}) lệch với trip_request.status ({trip_request.status!r})")


class ChatMessageOut(BaseModel):
    id: IdStr
    session_id: IdStr
    role: MessageRole
    content: str
    created_at: IsoDateTimeStr
    chips: List[ChipItem] = Field(default_factory=list)


class CreateSessionResponse(BaseModel):
    """POST /api/chat/sessions: phiên mới hoặc phiên đang dở của user."""
    session_id: IdStr
    status: SessionStatus
    trip_request: TripRequest

    @model_validator(mode="after")
    def _status_matches_trip_request(self):
        _require_same_status(self.status, self.trip_request)
        return self


class SessionDetailResponse(BaseModel):
    """GET /api/chat/sessions/{id}: khôi phục aside khi tải lại trang."""
    session_id: IdStr
    status: SessionStatus
    trip_request: TripRequest
    messages: List[ChatMessageOut] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_matches_trip_request(self):
        _require_same_status(self.status, self.trip_request)
        return self


class TextMessageInput(BaseModel):
    """Người dùng gõ chữ: {"type": "text", "content": "..."}"""
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    content: str = Field(..., max_length=MAX_MESSAGE_CHARS)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content không được để trống")
        return value


class ChipMessageInput(BaseModel):
    """Bấm nút gợi ý: {"type": "chip", "slot": "destination_mention", "value": "Sa Pa"} (Mục 7.2).
    Schema chỉ kiểm hình dạng; slot nào hợp lệ và giá trị có hợp lệ không do
    dialogue_engine.apply_chip_event quyết định (đã có kiểm tra, ném ValueError)."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["chip"]
    slot: str = Field(..., min_length=1)
    value: Union[bool, int, str]


# Đa hình theo trường `type`. Dùng làm kiểu body của route (FastAPI nhận trực tiếp) hoặc
# TypeAdapter(SendMessageInput).validate_python / validate_json ở nơi khác.
SendMessageInput = Annotated[Union[TextMessageInput, ChipMessageInput], Field(discriminator="type")]


class SendMessageResponse(BaseModel):
    """POST /api/chat/sessions/{id}/messages. Đủ slot quan trọng thì trả NGAY status "planning" + plan_task_id (Mục 8)."""
    session_id: IdStr
    status: SessionStatus
    bot_message: str
    trip_request: TripRequest
    chips: List[ChipItem] = Field(default_factory=list)
    is_ready: bool
    plan_task_id: Optional[str] = None

    @model_validator(mode="after")
    def _consistent(self):
        _require_same_status(self.status, self.trip_request)
        if self.status == "collecting" and self.is_ready:
            raise ValueError("is_ready=True nhưng status vẫn là 'collecting'")
        if self.status == "planning" and not self.plan_task_id:
            raise ValueError("status 'planning' bắt buộc kèm plan_task_id")
        return self


__all__ = [
    "MIN_PASSWORD_LENGTH", "MAX_PASSWORD_LENGTH", "MAX_EMAIL_LENGTH", "MAX_MESSAGE_CHARS",
    "SessionStatus", "MessageRole", "normalize_email",
    "UserRegisterRequest", "UserLoginRequest", "UserOut", "TokenResponse",
    "ChatMessageOut", "CreateSessionResponse", "SessionDetailResponse",
    "TextMessageInput", "ChipMessageInput", "SendMessageInput", "SendMessageResponse",
]
