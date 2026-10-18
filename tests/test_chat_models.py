"""
tests/test_chat_models.py
===============================================================================
Kiểm thử Lát 3 - Bước 1: schema Xác thực và Phiên chat (app/chat_models.py). PRODUCT_SPEC Mục 3.2, 7.2, 8.
Chạy: python -m pytest tests/test_chat_models.py
"""
import json
from datetime import datetime, timezone
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.chat_models import (
    MAX_EMAIL_LENGTH,
    MAX_MESSAGE_CHARS,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    ChatMessageOut,
    ChipMessageInput,
    CreateSessionResponse,
    SendMessageInput,
    SendMessageResponse,
    SessionDetailResponse,
    SessionStatus,
    TextMessageInput,
    TokenResponse,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)
from app.dialogue_models import ChipItem, TripRequest

PASSWORD = "x" * MIN_PASSWORD_LENGTH
NOW = "2026-10-18T10:00:00+00:00"
SEND = TypeAdapter(SendMessageInput)


def roundtrip(model):
    """model -> JSON text -> model; kết quả phải bằng nhau (serialize/deserialize không mất dữ liệu)."""
    text = model.model_dump_json()
    json.loads(text)  # phải là JSON hợp lệ
    return type(model).model_validate_json(text)


def trip(status="collecting", **critical) -> TripRequest:
    r = TripRequest(status=status)
    for k, v in critical.items():
        setattr(r.critical, k, v)
    return r


def chip(label="Sa Pa", slot="destination_mention", value=None) -> ChipItem:
    return ChipItem(id="chip_dest_sapa", label=label, slot=slot, value=label if value is None else value)


def user_out() -> UserOut:
    return UserOut(id=str(uuid4()), email="a@b.com", created_at=NOW)


# ═══════════════════════════════════════════════════════════════════════════════
# UserRegisterRequest
# ═══════════════════════════════════════════════════════════════════════════════
class TestRegister:
    def test_valid(self):
        r = UserRegisterRequest(email="user@example.com", password=PASSWORD)
        assert r.email == "user@example.com" and r.password == PASSWORD

    def test_email_is_trimmed_and_lowercased(self):  # Mục 3.2: email lưu chữ thường
        assert UserRegisterRequest(email="  User@Example.COM ", password=PASSWORD).email == "user@example.com"

    @pytest.mark.parametrize("email", [
        "user@example.com", "ten.ho+tag@sub.domain.vn", "a_b-c@x-y.co", "u@xn--p1ai.xn--p1ai",
    ])
    def test_accepts_reasonable_emails(self, email):
        assert UserRegisterRequest(email=email, password=PASSWORD).email == email.lower()

    @pytest.mark.parametrize("email", [
        "", "   ", "abc", "a@b", "a@@b.com", "a b@c.com", "@c.com", "a@", "a@.com", "a@c..com",
        "a..b@c.com", ".a@c.com", "a.@c.com", "a@-c.com", "a@c-.com", "a@c.c", "a@c.123",
        "người@ví-dụ.vn", "x" * MAX_EMAIL_LENGTH + "@b.com",
    ])
    def test_rejects_malformed_emails(self, email):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email=email, password=PASSWORD)

    @pytest.mark.parametrize("email", [None, 123, ["a@b.com"], True])
    def test_rejects_non_string_email(self, email):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email=email, password=PASSWORD)

    def test_rejects_password_too_short(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email="a@b.com", password="x" * (MIN_PASSWORD_LENGTH - 1))

    def test_accepts_password_of_exact_minimum_length(self):
        assert UserRegisterRequest(email="a@b.com", password="x" * MIN_PASSWORD_LENGTH)

    def test_rejects_password_too_long(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email="a@b.com", password="x" * (MAX_PASSWORD_LENGTH + 1))

    @pytest.mark.parametrize("password", [None, 12345678, ""])
    def test_rejects_missing_or_wrong_type_password(self, password):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email="a@b.com", password=password)

    def test_password_is_kept_verbatim_not_stripped_or_lowercased(self):
        pw = "  MẬt Khẩu  "
        assert UserRegisterRequest(email="a@b.com", password=pw).password == pw

    @pytest.mark.parametrize("extra", [{"role": "admin"}, {"is_admin": True}, {"id": "1"}])
    def test_rejects_unknown_fields(self, extra):  # chống mass-assignment; Mục 3.2: không phân quyền
        with pytest.raises(ValidationError):
            UserRegisterRequest(email="a@b.com", password=PASSWORD, **extra)

    def test_missing_fields(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(email="a@b.com")
        with pytest.raises(ValidationError):
            UserRegisterRequest(password=PASSWORD)

    def test_json_roundtrip(self):
        r = UserRegisterRequest(email="A@B.com", password=PASSWORD)
        assert roundtrip(r) == r


# ═══════════════════════════════════════════════════════════════════════════════
# UserLoginRequest
# ═══════════════════════════════════════════════════════════════════════════════
class TestLogin:
    def test_valid_and_email_normalised(self):
        r = UserLoginRequest(email=" User@Example.com ", password="p")
        assert r.email == "user@example.com" and r.password == "p"

    def test_does_not_reveal_password_policy_or_email_format(self):
        # Mục 3.2: sai đăng nhập báo CHUNG. Mật khẩu ngắn / email lạ vẫn qua schema để lớp auth trả 401.
        r = UserLoginRequest(email="khong-phai-email", password="1")
        assert r.email == "khong-phai-email"

    @pytest.mark.parametrize("kw", [
        {"email": "", "password": "p"}, {"email": "   ", "password": "p"}, {"email": "a@b.com", "password": ""},
        {"email": None, "password": "p"}, {"email": "a@b.com", "password": None}, {"email": "a@b.com"},
    ])
    def test_rejects_empty_or_missing(self, kw):
        with pytest.raises(ValidationError):
            UserLoginRequest(**kw)

    def test_rejects_oversized_password(self):
        with pytest.raises(ValidationError):
            UserLoginRequest(email="a@b.com", password="x" * (MAX_PASSWORD_LENGTH + 1))

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            UserLoginRequest(email="a@b.com", password="p", remember=True)

    def test_json_roundtrip(self):
        r = UserLoginRequest(email="a@b.com", password="p")
        assert roundtrip(r) == r


# ═══════════════════════════════════════════════════════════════════════════════
# UserOut / TokenResponse
# ═══════════════════════════════════════════════════════════════════════════════
class TestUserOutAndToken:
    def test_uuid_and_datetime_inputs_are_coerced_to_strings(self):
        uid = uuid4()
        u = UserOut(id=uid, email="a@b.com", created_at=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc))
        assert u.id == str(uid) and u.created_at == "2026-10-18T10:00:00+00:00"

    def test_integer_id_from_sqlite_is_coerced(self):
        assert UserOut(id=7, email="a@b.com", created_at=NOW).id == "7"

    @pytest.mark.parametrize("created_at", ["2026-10-18T10:00:00+00:00", "2026-10-18T10:00:00Z", "2026-10-18"])
    def test_accepts_iso_strings(self, created_at):
        assert UserOut(id="1", email="a@b.com", created_at=created_at).created_at == created_at

    @pytest.mark.parametrize("created_at", ["", "hôm qua", "18/10/2026", "2026-13-45", None, 1760000000, True])
    def test_rejects_non_iso_created_at(self, created_at):
        with pytest.raises(ValidationError):
            UserOut(id="1", email="a@b.com", created_at=created_at)

    @pytest.mark.parametrize("id_", ["", None, True, 1.5, ["1"]])
    def test_rejects_bad_id(self, id_):
        with pytest.raises(ValidationError):
            UserOut(id=id_, email="a@b.com", created_at=NOW)

    def test_password_hash_never_leaks(self):
        row = {"id": 1, "email": "a@b.com", "created_at": NOW, "password_hash": "$2b$12$secret"}
        u = UserOut(**row)
        assert "password_hash" not in u.model_dump()
        assert "secret" not in u.model_dump_json()

    def test_token_defaults_to_bearer_and_roundtrips(self):
        t = TokenResponse(access_token="abc.def.ghi", user=user_out())
        assert t.token_type == "bearer"
        assert roundtrip(t) == t

    def test_token_parses_nested_user_from_plain_dict(self):
        t = TokenResponse.model_validate({
            "access_token": "tok", "token_type": "bearer",
            "user": {"id": "u1", "email": "a@b.com", "created_at": NOW}})
        assert isinstance(t.user, UserOut) and t.user.id == "u1"

    @pytest.mark.parametrize("kw", [{"token_type": "basic"}, {"token_type": "Bearer"}, {"access_token": ""}])
    def test_token_rejects_bad_values(self, kw):
        data = {"access_token": "tok", "token_type": "bearer", "user": user_out()}
        data.update(kw)
        with pytest.raises(ValidationError):
            TokenResponse(**data)

    def test_token_requires_user(self):
        with pytest.raises(ValidationError):
            TokenResponse(access_token="tok")


# ═══════════════════════════════════════════════════════════════════════════════
# ChatMessageOut
# ═══════════════════════════════════════════════════════════════════════════════
class TestChatMessageOut:
    def test_roundtrip_with_chips(self):
        m = ChatMessageOut(id="m1", session_id="s1", role="assistant", content="Quý khách đi đâu?",
                           created_at=NOW, chips=[chip(), chip("Hà Giang", value="Hà Giang")])
        back = roundtrip(m)
        assert back == m and [c.label for c in back.chips] == ["Sa Pa", "Hà Giang"]

    def test_chips_default_empty_and_not_shared_between_instances(self):
        a = ChatMessageOut(id="1", session_id="s", role="user", content="hi", created_at=NOW)
        b = ChatMessageOut(id="2", session_id="s", role="user", content="hi", created_at=NOW)
        assert a.chips == [] and a.chips is not b.chips

    @pytest.mark.parametrize("role", ["system", "bot", "User", "", None])
    def test_rejects_bad_role(self, role):
        with pytest.raises(ValidationError):
            ChatMessageOut(id="1", session_id="s", role=role, content="x", created_at=NOW)

    def test_integer_ids_are_coerced(self):
        m = ChatMessageOut(id=5, session_id=9, role="user", content="x", created_at=NOW)
        assert (m.id, m.session_id) == ("5", "9")

    def test_chip_dicts_are_parsed_into_chip_items(self):
        m = ChatMessageOut.model_validate({
            "id": "1", "session_id": "s", "role": "assistant", "content": "x", "created_at": NOW,
            "chips": [{"id": "chip_dur_3", "label": "3 ngày", "slot": "duration_days", "value": 3}]})
        assert isinstance(m.chips[0], ChipItem) and m.chips[0].value == 3 and not isinstance(m.chips[0].value, bool)

    def test_malformed_chip_rejected(self):
        with pytest.raises(ValidationError):
            ChatMessageOut(id="1", session_id="s", role="assistant", content="x", created_at=NOW,
                           chips=[{"label": "thiếu id/slot/value"}])

    def test_empty_content_is_allowed(self):  # tin nhắn bot chỉ có chip vẫn hợp lệ
        assert ChatMessageOut(id="1", session_id="s", role="assistant", content="", created_at=NOW).content == ""


# ═══════════════════════════════════════════════════════════════════════════════
# CreateSessionResponse / SessionDetailResponse
# ═══════════════════════════════════════════════════════════════════════════════
class TestSessionResponses:
    def test_session_status_matches_trip_request_status(self):
        # tránh lệch hai nơi khai báo cùng một danh sách trạng thái
        assert set(get_args(SessionStatus)) == set(get_args(TripRequest.model_fields["status"].annotation))

    def test_create_session_roundtrip(self):
        r = trip(destination_mention="Sa Pa", duration_days=3)
        resp = CreateSessionResponse(session_id=r.session_id, status="collecting", trip_request=r)
        back = roundtrip(resp)
        assert back == resp
        assert back.trip_request.critical.destination_mention == "Sa Pa" and back.trip_request.critical.duration_days == 3

    def test_create_session_parses_plain_dict_trip_request(self):
        resp = CreateSessionResponse.model_validate({
            "session_id": "s1", "status": "collecting", "trip_request": trip().model_dump()})
        assert isinstance(resp.trip_request, TripRequest)

    @pytest.mark.parametrize("status", ["collecting", "ready", "planning", "planned", "error"])
    def test_every_status_accepted_when_consistent(self, status):
        r = trip(status=status)
        assert CreateSessionResponse(session_id="s", status=status, trip_request=r).status == status
        assert SessionDetailResponse(session_id="s", status=status, trip_request=r).status == status

    @pytest.mark.parametrize("status", ["done", "COLLECTING", "", None])
    def test_unknown_status_rejected(self, status):
        with pytest.raises(ValidationError):
            CreateSessionResponse(session_id="s", status=status, trip_request=trip())

    def test_status_mismatch_with_trip_request_rejected(self):
        with pytest.raises(ValidationError):
            CreateSessionResponse(session_id="s", status="ready", trip_request=trip("collecting"))
        with pytest.raises(ValidationError):
            SessionDetailResponse(session_id="s", status="planned", trip_request=trip("collecting"))

    def test_detail_roundtrip_with_messages_in_order(self):
        r = trip()
        msgs = [
            ChatMessageOut(id="1", session_id=r.session_id, role="user", content="du lịch miền núi phía bắc", created_at=NOW),
            ChatMessageOut(id="2", session_id=r.session_id, role="assistant", content="Quý khách muốn đi đâu?",
                           created_at=NOW, chips=[chip()]),
        ]
        detail = SessionDetailResponse(session_id=r.session_id, status="collecting", trip_request=r, messages=msgs)
        back = roundtrip(detail)
        assert back == detail
        assert [m.role for m in back.messages] == ["user", "assistant"] and back.messages[1].chips[0].label == "Sa Pa"

    def test_detail_messages_default_to_empty(self):
        assert SessionDetailResponse(session_id="s", status="collecting", trip_request=trip()).messages == []

    def test_required_fields(self):
        with pytest.raises(ValidationError):
            CreateSessionResponse(session_id="s", status="collecting")
        with pytest.raises(ValidationError):
            SessionDetailResponse(status="collecting", trip_request=trip())


# ═══════════════════════════════════════════════════════════════════════════════
# SendMessageInput (đa hình theo `type`)
# ═══════════════════════════════════════════════════════════════════════════════
class TestSendMessageInput:
    def test_parses_text_form(self):
        m = SEND.validate_python({"type": "text", "content": "du lịch miền núi phía bắc"})
        assert isinstance(m, TextMessageInput) and m.content == "du lịch miền núi phía bắc"

    def test_parses_chip_form(self):
        m = SEND.validate_python({"type": "chip", "slot": "destination_mention", "value": "Sa Pa"})
        assert isinstance(m, ChipMessageInput) and (m.slot, m.value) == ("destination_mention", "Sa Pa")

    def test_parses_both_forms_from_raw_json(self):
        t = SEND.validate_json('{"type": "text", "content": "từ Hà Nội"}')
        c = SEND.validate_json('{"type": "chip", "slot": "duration_days", "value": 3}')
        assert isinstance(t, TextMessageInput) and isinstance(c, ChipMessageInput)
        assert c.value == 3 and isinstance(c.value, int) and not isinstance(c.value, bool)

    def test_chip_value_types_are_preserved(self):
        assert SEND.validate_python({"type": "chip", "slot": "duration_days", "value": 3}).value == 3
        s = SEND.validate_python({"type": "chip", "slot": "duration_days", "value": "3"}).value
        assert s == "3" and isinstance(s, str)  # không tự ép; engine mới chuẩn hóa/kiểm tra
        b = SEND.validate_python({"type": "chip", "slot": "prefer_flight", "value": False}).value
        assert b is False

    def test_text_content_is_stripped(self):
        assert SEND.validate_python({"type": "text", "content": "  3 ngày \n"}).content == "3 ngày"

    @pytest.mark.parametrize("content", ["", "   ", "\n\t", None, 123])
    def test_rejects_blank_or_wrong_type_text(self, content):
        with pytest.raises(ValidationError):
            SEND.validate_python({"type": "text", "content": content})

    def test_text_length_limit(self):
        assert SEND.validate_python({"type": "text", "content": "a" * MAX_MESSAGE_CHARS})
        with pytest.raises(ValidationError):
            SEND.validate_python({"type": "text", "content": "a" * (MAX_MESSAGE_CHARS + 1)})

    @pytest.mark.parametrize("payload", [
        {"type": "chip", "value": "Sa Pa"},                              # thiếu slot
        {"type": "chip", "slot": "destination_mention"},                 # thiếu value
        {"type": "chip", "slot": "", "value": "Sa Pa"},                  # slot rỗng
        {"type": "chip", "slot": "destination_mention", "value": None},  # value null
        {"type": "chip", "slot": "destination_mention", "value": ["Sa Pa"]},
        {"type": "chip", "slot": 5, "value": "x"},
    ])
    def test_rejects_malformed_chip(self, payload):
        with pytest.raises(ValidationError):
            SEND.validate_python(payload)

    @pytest.mark.parametrize("payload", [
        {"type": "text"},                              # thiếu content
        {"content": "xin chào"},                       # thiếu type
        {"type": "voice", "content": "xin chào"},      # type lạ
        {"type": "TEXT", "content": "xin chào"},       # phân biệt hoa/thường
        {},
        {"type": None},
    ])
    def test_rejects_missing_or_unknown_type(self, payload):
        with pytest.raises(ValidationError):
            SEND.validate_python(payload)

    @pytest.mark.parametrize("payload", [
        {"type": "text", "content": "hi", "slot": "destination_mention"},          # text lẫn trường chip
        {"type": "chip", "slot": "duration_days", "value": 3, "content": "3 ngày"},  # chip lẫn trường text
        {"type": "text", "content": "hi", "user_id": "someone-else"},
    ])
    def test_rejects_mixed_or_unknown_fields(self, payload):
        with pytest.raises(ValidationError):
            SEND.validate_python(payload)

    def test_non_object_payloads_rejected(self):
        for bad in ("chip", None, 3, ["text"]):
            with pytest.raises(ValidationError):
                SEND.validate_python(bad)

    def test_dump_of_chip_input_feeds_dialogue_engine_directly(self):
        # Hợp đồng liên lớp: dạng dict sau khi parse là đúng "sự kiện chip" mà apply_chip_event nhận (Mục 7.2)
        from app.services.dialogue_engine import apply_chip_event
        parsed = SEND.validate_json('{"type": "chip", "slot": "destination_mention", "value": "Sa Pa"}')
        out = apply_chip_event(TripRequest(), parsed.model_dump())
        assert out.critical.destination_mention == "Sa Pa"

    def test_input_roundtrip(self):
        for payload in ({"type": "text", "content": "xin chào"},
                        {"type": "chip", "slot": "duration_days", "value": 4}):
            m = SEND.validate_python(payload)
            assert SEND.validate_json(SEND.dump_json(m)) == m


# ═══════════════════════════════════════════════════════════════════════════════
# SendMessageResponse
# ═══════════════════════════════════════════════════════════════════════════════
class TestSendMessageResponse:
    def test_collecting_roundtrip_with_chips(self):
        r = trip(destination_mention="Sa Pa")
        resp = SendMessageResponse(
            session_id=r.session_id, status="collecting", bot_message="Quý khách dự định khởi hành từ tỉnh/thành nào?",
            trip_request=r, chips=[chip("Hà Nội", "origin_mention")], is_ready=False)
        back = roundtrip(resp)
        assert back == resp and back.plan_task_id is None and back.chips[0].slot == "origin_mention"

    def test_chips_default_to_empty_list(self):
        r = trip()
        resp = SendMessageResponse(session_id="s", status="collecting", bot_message="?", trip_request=r, is_ready=False)
        assert resp.chips == [] and resp.plan_task_id is None

    def test_planning_returns_task_id_immediately(self):  # Mục 8: trả ngay planning + plan_task_id
        r = trip("planning", destination_mention="Sa Pa", origin_mention="Hà Nội", duration_days=3)
        r.plan_task_id = "task-123"
        resp = SendMessageResponse(session_id=r.session_id, status="planning", bot_message="Đang lên lịch trình...",
                                   trip_request=r, is_ready=True, plan_task_id="task-123")
        back = roundtrip(resp)
        assert back == resp and back.is_ready is True and back.plan_task_id == "task-123"

    @pytest.mark.parametrize("task_id", [None, ""])
    def test_planning_without_task_id_rejected(self, task_id):
        with pytest.raises(ValidationError):
            SendMessageResponse(session_id="s", status="planning", bot_message="x",
                                trip_request=trip("planning"), is_ready=True, plan_task_id=task_id)

    def test_collecting_cannot_be_ready(self):
        with pytest.raises(ValidationError):
            SendMessageResponse(session_id="s", status="collecting", bot_message="x",
                                trip_request=trip("collecting"), is_ready=True)

    def test_status_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            SendMessageResponse(session_id="s", status="ready", bot_message="x",
                                trip_request=trip("collecting"), is_ready=True)

    @pytest.mark.parametrize("missing", ["session_id", "status", "bot_message", "trip_request", "is_ready"])
    def test_required_fields(self, missing):
        data = dict(session_id="s", status="collecting", bot_message="x", trip_request=trip(), is_ready=False)
        del data[missing]
        with pytest.raises(ValidationError):
            SendMessageResponse(**data)

    def test_serialised_json_shape_for_frontend(self):
        r = trip()
        resp = SendMessageResponse(session_id="s", status="collecting", bot_message="x", trip_request=r,
                                   chips=[chip()], is_ready=False)
        data = json.loads(resp.model_dump_json())
        assert set(data) == {"session_id", "status", "bot_message", "trip_request", "chips", "is_ready", "plan_task_id"}
        assert data["chips"][0] == {"id": "chip_dest_sapa", "label": "Sa Pa", "slot": "destination_mention", "value": "Sa Pa"}
        assert data["trip_request"]["critical"] == {"destination_mention": None, "origin_mention": None, "duration_days": None}
