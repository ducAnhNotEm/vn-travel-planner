"""
tests/test_chat_routers.py
===============================================================================
Kiểm thử Lát 3 - Bước 4: app/routers/auth_router.py và app/routers/chat_router.py. PRODUCT_SPEC Mục 3, 7.2, 8.

- Dùng FastAPI + TestClient thật, nhưng app được dựng RIÊNG (chỉ hai router) với DB SQLite tạm (tmp_path).
- NLU, Gazetteer, planner được thay bằng bản giả qua app.dependency_overrides: test không phụ thuộc dữ liệu
  gazetteer thật hay dịch vụ NLU, và đếm được số lần NLU được gọi (chip KHÔNG được gọi NLU).
- dialogue_engine / dialogue_state / nlu_adapter là mã THẬT (đọc config/dialogue.json thật).
Chạy: python -m pytest tests/test_chat_routers.py
"""
import re
import sqlite3
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat_models import MAX_MESSAGE_CHARS, MIN_PASSWORD_LENGTH
from app.routers import auth_router, chat_router
from app.services import auth_service, chat_storage as cs

PASSWORD = "matkhau-hop-le-123"
FAIL = object()  # kịch bản NLU: trả {"success": False}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(cs.DB_PATH_ENV, str(tmp_path / "routers_test.db"))
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    monkeypatch.delenv("AUTH_TOKEN_TTL_SECONDS", raising=False)
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    return tmp_path


# ───────────────────────────── Bản giả ─────────────────────────────
class FakeNLU:
    """script: {câu_người_dùng: dict extracted | FAIL | Exception}. Câu lạ -> không trích được gì (thành công, rỗng)."""

    def __init__(self, script=None):
        self.script, self.calls = script or {}, []

    def __call__(self, prompt):
        self.calls.append(prompt)
        outcome = self.script.get(prompt, {})
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is FAIL:
            return {"success": False, "error": "giả lập"}
        return {"success": True, "extracted": outcome}


class FakeGazetteer:
    def same_entity(self, a, b):
        norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
        return norm(a) == norm(b)

    def suggest_destinations_by_hints(self, destination_regions, terrain_types, limit, exclude, avoid):
        return [{"label": x} for x in ("Sa Pa", "Hà Giang", "Mộc Châu")][:limit]


class FakePlanner:
    def __init__(self, task_id="task-123", error=None):
        self.task_id, self.error, self.calls = task_id, error, []

    def __call__(self, trip_request, user_id):
        self.calls.append((trip_request, user_id))
        if self.error:
            raise self.error
        return self.task_id


def make_app(nlu=None, planner=None):
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
    app.include_router(chat_router.router, prefix="/api/chat", tags=["chat"])
    nlu = nlu or FakeNLU()
    app.dependency_overrides[chat_router.get_gazetteer] = lambda: FakeGazetteer()
    app.dependency_overrides[chat_router.get_nlu_parser] = lambda: nlu
    if planner is not None:
        app.dependency_overrides[chat_router.get_plan_starter] = lambda: planner
    return app, nlu


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def signup(client, email="a@example.com", password=PASSWORD):
    resp = client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.json()
    return resp.json()["access_token"]


def start_session(client, token):
    resp = client.post("/api/chat/sessions", headers=bearer(token))
    assert resp.status_code == 200, resp.json()
    return resp.json()["session_id"]


def say(client, token, session_id, text):
    return client.post(f"/api/chat/sessions/{session_id}/messages", headers=bearer(token),
                       json={"type": "text", "content": text})


def click(client, token, session_id, slot, value):
    return client.post(f"/api/chat/sessions/{session_id}/messages", headers=bearer(token),
                       json={"type": "chip", "slot": slot, "value": value})


def chip_values(body, slot):
    return [c["value"] for c in body["chips"] if c["slot"] == slot]


def raw(sql, params=()):
    cs.init_db()
    with closing(sqlite3.connect(cs.get_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


# ═════════════════════════════ AUTH ═════════════════════════════
class TestRegister:
    def test_success_returns_token_response_201(self):
        app, _ = make_app()
        resp = TestClient(app).post("/api/auth/register", json={"email": "A@Example.com", "password": PASSWORD})
        assert resp.status_code == 201
        body = resp.json()
        assert body["token_type"] == "bearer" and len(body["access_token"]) >= 40
        assert body["user"]["email"] == "a@example.com"
        assert "password" not in str(body)

    def test_sets_httponly_samesite_lax_cookie_matching_token_ttl(self):
        app, _ = make_app()
        resp = TestClient(app).post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
        cookie = resp.headers.get("set-cookie", "").lower()
        assert auth_service.COOKIE_NAME in cookie
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        assert f"max-age={auth_service.token_ttl_seconds()}" in cookie

    def test_response_not_cacheable(self):
        app, _ = make_app()
        resp = TestClient(app).post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
        assert resp.headers.get("cache-control") == "no-store"

    def test_secure_flag_when_enabled(self, monkeypatch):
        monkeypatch.setenv("AUTH_COOKIE_SECURE", "1")
        app, _ = make_app()
        resp = TestClient(app).post("/api/auth/register", json={"email": "a@example.com", "password": PASSWORD})
        cookie = resp.headers.get("set-cookie", "").lower()
        # Tách "samesite" ra trước khi kiểm "secure" để tránh false positive
        parts = [p.strip() for p in cookie.split(";")]
        has_secure = any(p == "secure" for p in parts)
        assert has_secure

    def test_token_ttl_seconds_default_and_env(self, monkeypatch):
        assert auth_service.token_ttl_seconds() == 30 * 24 * 3600
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "120")
        assert auth_service.token_ttl_seconds() == 120

    def test_registered_user_is_logged_in_immediately(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        assert client.get("/api/auth/me", headers=bearer(token)).json()["email"] == "a@example.com"

    def test_duplicate_email_409(self):
        app, _ = make_app()
        client = TestClient(app)
        signup(client)
        resp = client.post("/api/auth/register", json={"email": "a@example.com", "password": "mat-khau-khac-99"})
        assert resp.status_code == 409
        assert len(raw("SELECT * FROM users")) == 1

    def test_duplicate_email_case_insensitive_409(self):
        app, _ = make_app()
        client = TestClient(app)
        signup(client, "a@example.com")
        assert client.post("/api/auth/register",
                           json={"email": "A@EXAMPLE.COM", "password": PASSWORD}).status_code == 409

    @pytest.mark.parametrize("body", [
        {"email": "khong-hop-le", "password": PASSWORD},
        {"email": "a@example.com", "password": "x" * (MIN_PASSWORD_LENGTH - 1)},
        {"email": "a@example.com"},
        {"password": PASSWORD},
        {"email": "a@example.com", "password": PASSWORD, "role": "admin"},  # mass-assignment
    ])
    def test_invalid_payload_422_and_no_user_created(self, body):
        app, _ = make_app()
        assert TestClient(app).post("/api/auth/register", json=body).status_code == 422
        assert raw("SELECT * FROM users") == []


class TestLogin:
    def _registered(self):
        app, _ = make_app()
        signup(TestClient(app))
        return app

    def test_correct_credentials_200_token_and_cookie(self):
        app = self._registered()
        resp = TestClient(app).post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer" and body["user"]["email"] == "a@example.com"
        cookie = resp.headers.get("set-cookie", "").lower()
        assert auth_service.COOKIE_NAME in cookie
        assert "httponly" in cookie and "samesite=lax" in cookie

    def test_email_case_insensitive(self):
        app = self._registered()
        assert TestClient(app).post("/api/auth/login",
                                    json={"email": " A@EXAMPLE.com ", "password": PASSWORD}).status_code == 200

    def test_wrong_password_401_no_cookie(self):
        app = self._registered()
        resp = TestClient(app).post("/api/auth/login", json={"email": "a@example.com", "password": "sai-mat-khau"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "email hoặc mật khẩu không đúng"
        assert "set-cookie" not in resp.headers

    def test_unknown_email_401_same_message(self):
        app = self._registered()
        resp = TestClient(app).post("/api/auth/login", json={"email": "khong-co@example.com", "password": PASSWORD})
        assert resp.status_code == 401 and resp.json()["detail"] == "email hoặc mật khẩu không đúng"

    @pytest.mark.parametrize("body", [{"email": "a@example.com"}, {"password": PASSWORD}, {},
                                      {"email": "a@example.com", "password": PASSWORD, "x": 1}])
    def test_malformed_body_422(self, body):
        app = self._registered()
        assert TestClient(app).post("/api/auth/login", json=body).status_code == 422

    def test_each_login_new_token(self):
        app = self._registered()
        c = TestClient(app)
        t1 = c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["access_token"]
        t2 = c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["access_token"]
        assert t1 != t2


class TestMeAndLogout:
    def test_me_requires_auth(self):
        app, _ = make_app()
        resp = TestClient(app).get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"

    def test_me_with_bearer(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        body = TestClient(app).get("/api/auth/me", headers=bearer(token)).json()
        assert body["email"] == "a@example.com" and "password" not in str(body)

    def test_me_with_cookie_only(self):
        app, _ = make_app()
        client = TestClient(app)
        signup(client)  # cookie nằm trong "jar" của client
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200 and resp.json()["email"] == "a@example.com"

    def test_me_invalid_token_401(self):
        app, _ = make_app()
        assert TestClient(app).get("/api/auth/me", headers=bearer("sai")).status_code == 401

    def test_logout_requires_auth(self):
        app, _ = make_app()
        assert TestClient(app).post("/api/auth/logout").status_code == 401

    def test_logout_revokes_token_and_clears_cookie(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        resp = client.post("/api/auth/logout", headers=bearer(token))
        assert resp.status_code == 200 and resp.json() == {"ok": True}
        cookie = resp.headers.get("set-cookie", "").lower()
        assert auth_service.COOKIE_NAME in cookie and 'max-age=0' in cookie
        assert TestClient(app).get("/api/auth/me", headers=bearer(token)).status_code == 401

    def test_logout_via_cookie_revokes_that_token(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        assert client.post("/api/auth/logout").status_code == 200
        assert TestClient(app).get("/api/auth/me", headers=bearer(token)).status_code == 401

    def test_logout_revokes_only_current_token(self):
        app, _ = make_app()
        client = TestClient(app)
        t1 = signup(client)
        t2 = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["access_token"]
        client.post("/api/auth/logout", headers=bearer(t1))
        assert TestClient(app).get("/api/auth/me", headers=bearer(t1)).status_code == 401
        assert TestClient(app).get("/api/auth/me", headers=bearer(t2)).status_code == 200

    def test_second_logout_with_same_token_401(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        client.post("/api/auth/logout", headers=bearer(token))
        assert TestClient(app).post("/api/auth/logout", headers=bearer(token)).status_code == 401


# ═════════════════════════════ CHAT: bảo mật ═════════════════════════════
class TestChatRequiresAuth:
    @pytest.mark.parametrize("method,url", [
        ("POST", "/api/chat/sessions"),
        ("GET", "/api/chat/sessions/khong-ton-tai"),
        ("POST", "/api/chat/sessions/khong-ton-tai/messages"),
    ])
    def test_unauthenticated_401(self, method, url):
        app, nlu = make_app()
        client = TestClient(app)
        body = {"type": "text", "content": "xin chào"}
        resp = client.post(url, json=body) if method == "POST" else client.get(url)
        assert resp.status_code == 401  # kể cả session không tồn tại: xác thực đi trước, không lộ 404
        assert resp.headers.get("www-authenticate") == "Bearer"
        assert nlu.calls == []

    def test_invalid_and_revoked_token_401(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        assert TestClient(app).post("/api/chat/sessions", headers=bearer("sai")).status_code == 401
        auth_service.revoke_token(token)
        assert TestClient(app).get(f"/api/chat/sessions/{sid}", headers=bearer(token)).status_code == 401

    def test_cookie_authenticates_chat(self):
        app, _ = make_app()
        client = TestClient(app)
        signup(client)
        assert client.post("/api/chat/sessions").status_code == 200

    def test_no_chat_data_created_when_unauthenticated(self):
        app, _ = make_app()
        TestClient(app).post("/api/chat/sessions")
        assert raw("SELECT * FROM chat_sessions") == []


class TestMultiTenantIsolation:
    def _two_users(self):
        app, nlu = make_app(FakeNLU({"đi Sa Pa": {"destination": "Sa Pa"}}))
        client = TestClient(app)
        a = signup(client, "a@example.com")
        b = signup(client, "b@example.com")
        return app, nlu, client, a, b

    def test_other_user_cannot_read_session_403(self):
        app, nlu, client, a, b = self._two_users()
        sid = start_session(client, a)
        resp = client.get(f"/api/chat/sessions/{sid}", headers=bearer(b))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Không có quyền truy cập phiên này"

    def test_other_user_cannot_send_text_403_and_nothing_changes(self):
        app, nlu, client, a, b = self._two_users()
        sid = start_session(client, a)
        assert say(client, b, sid, "đi Sa Pa").status_code == 403
        assert nlu.calls == []  # bị từ chối trước khi tốn công NLU
        detail = client.get(f"/api/chat/sessions/{sid}", headers=bearer(a)).json()
        assert detail["messages"] == [] and detail["trip_request"]["critical"]["destination_mention"] is None
        assert raw("SELECT * FROM chat_messages") == []

    def test_other_user_cannot_send_chip_403_and_nothing_changes(self):
        app, nlu, client, a, b = self._two_users()
        sid = start_session(client, a)
        assert click(client, b, sid, "duration_days", 3).status_code == 403
        detail = client.get(f"/api/chat/sessions/{sid}", headers=bearer(a)).json()
        assert detail["trip_request"]["critical"]["duration_days"] is None and detail["messages"] == []

    def test_each_user_gets_own_session(self):
        app, nlu, client, a, b = self._two_users()
        assert start_session(client, a) != start_session(client, b)

    def test_unknown_session_404_for_get_and_post(self):
        app, nlu, client, a, b = self._two_users()
        assert client.get("/api/chat/sessions/khong-co", headers=bearer(a)).status_code == 404
        assert say(client, a, "khong-co", "xin chào").status_code == 404
        assert click(client, a, "khong-co", "duration_days", 3).status_code == 404


# ═════════════════════════════ CHAT: phiên ═════════════════════════════
class TestSessions:
    def test_create_returns_empty_collecting_session(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        body = client.post("/api/chat/sessions", headers=bearer(token)).json()
        assert body["status"] == "collecting"
        tr = body["trip_request"]
        assert tr["status"] == "collecting" and tr["turn"] == 0
        assert tr["critical"] == {"destination_mention": None, "origin_mention": None, "duration_days": None}

    def test_create_is_idempotent_returns_unfinished_session(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        assert start_session(client, token) == start_session(client, token)
        assert len(raw("SELECT * FROM chat_sessions")) == 1

    def test_get_session_empty(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        body = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()
        assert body["session_id"] == sid and body["messages"] == [] and body["status"] == "collecting"


# ═════════════════════════════ CHAT: tin nhắn chữ (NLU) ═════════════════════════════
class TestTextMessages:
    def test_partial_info_asks_next_question_with_chips(self):
        app, nlu = make_app(FakeNLU({"đi Sa Pa 3 ngày": {"destination": "Sa Pa", "duration_days": 3}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        resp = say(client, token, sid, "đi Sa Pa 3 ngày")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "collecting" and body["is_ready"] is False and body["plan_task_id"] is None
        tr = body["trip_request"]
        assert tr["critical"]["destination_mention"] == "Sa Pa" and tr["critical"]["duration_days"] == 3
        assert "khởi hành" in body["bot_message"]  # chỉ còn thiếu điểm xuất phát
        origins = chip_values(body, "origin_mention")
        assert origins[0] == "CURRENT_LOCATION" and "Hà Nội" in origins
        assert nlu.calls == ["đi Sa Pa 3 ngày"]

    def test_vague_request_asks_destination_and_origin_max_two_questions(self):
        app, _ = make_app(FakeNLU({"miền núi phía bắc": {"destination_regions": ["NORTH"], "terrain_types": ["MOUNTAIN"]}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        body = say(client, token, sid, "miền núi phía bắc").json()
        assert body["status"] == "collecting"
        assert body["trip_request"]["hints"]["destination_regions"] == ["NORTH"]
        assert body["trip_request"]["critical"]["destination_mention"] is None  # vùng/địa hình chưa đủ (Mục 4.2)
        assert body["trip_request"]["asked"] == ["destination_mention", "origin_mention"]  # tối đa 2 câu/lượt
        assert chip_values(body, "destination_mention") == ["Sa Pa", "Hà Giang", "Mộc Châu"]
        assert "khởi hành" in body["bot_message"] and "điểm cụ thể" in body["bot_message"]

    def test_all_critical_slots_ready_without_planner(self):
        app, _ = make_app(FakeNLU({"Sa Pa từ Hà Nội 3 ngày": {"destination": "Sa Pa", "origin": "Hà Nội", "duration_days": 3}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        body = say(client, token, sid, "Sa Pa từ Hà Nội 3 ngày").json()
        assert body["status"] == "ready" and body["is_ready"] is True
        assert body["plan_task_id"] is None and body["chips"] == []
        assert client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()["status"] == "ready"

    def test_ready_session_is_still_active_and_resumed(self):
        app, _ = make_app(FakeNLU({"đủ": {"destination": "Sa Pa", "origin": "Hà Nội", "duration_days": 3}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "đủ")
        assert start_session(client, token) == sid

    def test_user_changes_mind_new_value_overwrites(self):
        app, _ = make_app(FakeNLU({"đi Sa Pa": {"destination": "Sa Pa"}, "thôi đi Đà Lạt": {"destination": "Đà Lạt"}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "đi Sa Pa")
        body = say(client, token, sid, "thôi đi Đà Lạt").json()
        assert body["trip_request"]["critical"]["destination_mention"] == "Đà Lạt"

    def test_empty_nlu_result_does_not_erase_previous_slots(self):
        app, _ = make_app(FakeNLU({"đi Sa Pa": {"destination": "Sa Pa"}}))  # "ừm" -> không trích được gì
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "đi Sa Pa")
        body = say(client, token, sid, "ừm").json()
        assert body["trip_request"]["critical"]["destination_mention"] == "Sa Pa"

    def test_exclusions_and_pins_flow_into_extra(self):
        app, _ = make_app(FakeNLU({"x": {"destination": "Sa Pa", "excluded_destinations": ["Hạ Long"],
                                         "must_visit_places": ["Fansipan"], "excluded_activities": ["trekking"]}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        extra = say(client, token, sid, "x").json()["trip_request"]["extra"]
        assert extra["excluded_mentions"] == ["Hạ Long"] and extra["pinned_mentions"] == ["Fansipan"]
        assert extra["excluded_activities"] == ["trekking"]

    def test_origin_equal_destination_is_reported_and_asked_again(self):
        app, _ = make_app(FakeNLU({"đi Hà Nội từ Hà Nội 2 ngày": {"destination": "Hà Nội", "origin": "Hà Nội", "duration_days": 2}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        body = say(client, token, sid, "đi Hà Nội từ Hà Nội 2 ngày").json()
        assert body["status"] == "collecting" and body["is_ready"] is False
        assert "trùng nhau" in body["bot_message"]
        assert body["chips"] and all(c["slot"] == "destination_mention" for c in body["chips"])

    def test_turn_counter_increments_once_per_message(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        turns = [say(client, token, sid, "a").json()["trip_request"]["turn"],
                 click(client, token, sid, "duration_days", 2).json()["trip_request"]["turn"],
                 say(client, token, sid, "b").json()["trip_request"]["turn"]]
        assert turns == [1, 2, 3]

    def test_text_is_stripped_and_stored(self):
        app, nlu = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "   đi Sa Pa   ")
        assert nlu.calls == ["đi Sa Pa"]
        msgs = raw("SELECT content FROM chat_messages WHERE role='user'")
        assert msgs[0]["content"] == "đi Sa Pa"

    @pytest.mark.parametrize("body", [
        {"type": "text", "content": "   "},
        {"type": "text"},
        {"type": "text", "content": "x" * (MAX_MESSAGE_CHARS + 1)},
        {"type": "text", "content": "hi", "role": "admin"},
        {"type": "voice", "content": "hi"},
        {"content": "hi"},
        {"type": "chip", "slot": "destination_mention"},
        {"type": "chip", "slot": "destination_mention", "value": "Sa Pa", "extra": 1},
    ])
    def test_invalid_body_422_and_nothing_persisted(self, body):
        app, nlu = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        resp = client.post(f"/api/chat/sessions/{sid}/messages", headers=bearer(token), json=body)
        assert resp.status_code == 422
        assert nlu.calls == [] and raw("SELECT * FROM chat_messages") == []


class TestNluFailureIsGraceful:
    @pytest.mark.parametrize("outcome", [FAIL, RuntimeError("LLM sập"), ImportError("thiếu module")])
    def test_failure_still_replies_and_keeps_state(self, outcome):
        app, nlu = make_app(FakeNLU({"đi Sa Pa": {"destination": "Sa Pa"}, "câu lỗi": outcome}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "đi Sa Pa")
        resp = say(client, token, sid, "câu lỗi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["bot_message"].startswith("Xin lỗi, tôi chưa hiểu rõ")
        assert body["status"] == "collecting" and body["chips"]  # vẫn hỏi tiếp, vẫn có chip
        assert body["trip_request"]["critical"]["destination_mention"] == "Sa Pa"  # không mất slot cũ
        assert body["trip_request"]["turn"] == 2

    def test_failed_turn_is_still_saved_in_history(self):
        app, _ = make_app(FakeNLU({"câu lỗi": FAIL}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "câu lỗi")
        msgs = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]


# ═════════════════════════════ CHAT: chip (bỏ qua NLU) ═════════════════════════════
class TestChipEvents:
    def _vague_session(self):
        app, nlu = make_app(FakeNLU({"miền núi phía bắc": {"destination_regions": ["NORTH"], "terrain_types": ["MOUNTAIN"]}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "miền núi phía bắc")
        nlu.calls.clear()
        return app, nlu, client, token, sid

    def test_chip_fills_slot_and_returns_next_question_without_nlu(self):
        app, nlu, client, token, sid = self._vague_session()
        resp = click(client, token, sid, "destination_mention", "Sa Pa")
        assert resp.status_code == 200
        body = resp.json()
        tr = body["trip_request"]
        assert tr["critical"]["destination_mention"] == "Sa Pa"
        assert tr["hints"]["destination_regions"] == [] and tr["hints"]["terrain_types"] == []  # quy tắc 4
        assert body["status"] == "collecting"
        assert "khởi hành" in body["bot_message"] and "mấy ngày" in body["bot_message"]  # câu kế tiếp
        assert chip_values(body, "duration_days") == [1, 2, 3, 4, 5]
        assert nlu.calls == []  # Mục 7.2: KHÔNG gọi NLU

    def test_chip_sequence_reaches_ready(self):
        app, nlu, client, token, sid = self._vague_session()
        click(client, token, sid, "destination_mention", "Sa Pa")
        mid = click(client, token, sid, "origin_mention", "Hà Nội").json()
        assert mid["status"] == "collecting" and "mấy ngày" in mid["bot_message"]
        done = click(client, token, sid, "duration_days", 3).json()
        assert done["status"] == "ready" and done["is_ready"] is True and done["chips"] == []
        assert done["trip_request"]["critical"] == {"destination_mention": "Sa Pa", "origin_mention": "Hà Nội", "duration_days": 3}
        assert nlu.calls == []

    def test_current_location_chip(self):
        app, nlu, client, token, sid = self._vague_session()
        body = click(client, token, sid, "origin_mention", "CURRENT_LOCATION").json()
        assert body["trip_request"]["critical"]["origin_mention"] == "CURRENT_LOCATION"
        msgs = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()["messages"]
        assert msgs[-2]["role"] == "user" and msgs[-2]["content"] == "Vị trí hiện tại"

    def test_chip_shows_as_user_message_with_readable_text(self):
        app, nlu, client, token, sid = self._vague_session()
        click(client, token, sid, "destination_mention", "Sa Pa")
        click(client, token, sid, "duration_days", 3)
        users = [m["content"] for m in client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()["messages"]
                 if m["role"] == "user"]
        assert users == ["miền núi phía bắc", "Sa Pa", "3 ngày"]

    def test_numeric_string_value_accepted(self):
        app, nlu, client, token, sid = self._vague_session()
        body = click(client, token, sid, "duration_days", "4").json()
        assert body["trip_request"]["critical"]["duration_days"] == 4

    def test_chip_changing_mind_overwrites(self):
        app, nlu, client, token, sid = self._vague_session()
        click(client, token, sid, "duration_days", 2)
        body = click(client, token, sid, "duration_days", 5).json()
        assert body["trip_request"]["critical"]["duration_days"] == 5

    @pytest.mark.parametrize("slot,value", [
        ("khong_co_slot", "x"),
        ("excluded_activities", "trekking"),   # có trong schema nhưng không phải slot chip
        ("duration_days", 0),
        ("duration_days", 99),
        ("duration_days", "abc"),
        ("duration_days", True),
        ("destination_mention", "   "),
        ("prefer_flight", "maybe"),
        ("group_size", 0),
    ])
    def test_invalid_chip_422_and_nothing_persisted(self, slot, value):
        app, nlu, client, token, sid = self._vague_session()
        before = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()
        resp = click(client, token, sid, slot, value)
        assert resp.status_code == 422
        assert resp.json()["detail"].startswith("Sự kiện chip không hợp lệ")
        after = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()
        assert after == before  # không đổi state, không thêm tin nhắn, không tăng turn
        assert nlu.calls == []

    def test_optional_slots_via_chip(self):
        app, nlu, client, token, sid = self._vague_session()
        click(client, token, sid, "group_size", 4)
        body = click(client, token, sid, "prefer_flight", False).json()
        assert body["trip_request"]["extra"]["group_size"] == 4
        assert body["trip_request"]["extra"]["prefer_flight"] is False

    def test_destination_equals_origin_chip_conflict(self):
        app, nlu, client, token, sid = self._vague_session()
        click(client, token, sid, "destination_mention", "Hà Nội")
        body = click(client, token, sid, "origin_mention", "Hà Nội").json()
        assert body["status"] == "collecting" and "trùng nhau" in body["bot_message"]


# ═════════════════════════════ CHAT: tự lên lịch ═════════════════════════════
FULL = {"destination": "Sa Pa", "origin": "Hà Nội", "duration_days": 3}


class TestPlanning:
    def _ready(self, planner):
        app, nlu = make_app(FakeNLU({"đủ": FULL}), planner=planner)
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        return client, token, sid

    def test_ready_starts_planner_and_returns_planning_with_task_id(self):
        planner = FakePlanner("task-abc")
        client, token, sid = self._ready(planner)
        resp = say(client, token, sid, "đủ")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "planning" and body["is_ready"] is True and body["plan_task_id"] == "task-abc"
        assert body["trip_request"]["status"] == "planning"
        assert body["chips"] == []
        assert len(planner.calls) == 1
        trip, user_id = planner.calls[0]
        assert trip.critical.duration_days == 3 and trip.critical.destination_mention == "Sa Pa"
        assert user_id == client.get("/api/auth/me", headers=bearer(token)).json()["id"]

    def test_planner_not_started_while_collecting(self):
        planner = FakePlanner()
        app, _ = make_app(FakeNLU({"thiếu": {"destination": "Sa Pa"}}), planner=planner)
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        assert say(client, token, sid, "thiếu").json()["status"] == "collecting"
        assert planner.calls == []

    def test_planning_session_is_closed_and_new_session_is_created(self):
        client, token, sid = self._ready(FakePlanner())
        say(client, token, sid, "đủ")
        assert client.get(f"/api/chat/sessions/{sid}", headers=bearer(token)).json()["status"] == "planning"
        new_sid = start_session(client, token)
        assert new_sid != sid
        assert client.get(f"/api/chat/sessions/{new_sid}", headers=bearer(token)).json()["status"] == "collecting"

    def test_posting_to_planning_session_409_and_planner_not_restarted(self):
        planner = FakePlanner()
        client, token, sid = self._ready(planner)
        say(client, token, sid, "đủ")
        assert say(client, token, sid, "đủ").status_code == 409
        assert click(client, token, sid, "duration_days", 2).status_code == 409
        assert len(planner.calls) == 1  # chống khởi động planner hai lần khi bấm đúp
        assert len(raw("SELECT * FROM chat_messages WHERE session_id=?", (sid,))) == 2

    def test_planner_failure_keeps_ready_and_does_not_500(self):
        planner = FakePlanner(error=RuntimeError("hàng đợi sập"))
        client, token, sid = self._ready(planner)
        resp = say(client, token, sid, "đủ")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready" and body["is_ready"] is True and body["plan_task_id"] is None
        assert start_session(client, token) == sid  # vẫn là phiên đang dở, thử lại được

    def test_planner_returning_none_keeps_ready(self):
        client, token, sid = self._ready(FakePlanner(task_id=None))
        body = say(client, token, sid, "đủ").json()
        assert body["status"] == "ready" and body["plan_task_id"] is None

    def test_planning_via_chip_path(self):
        planner = FakePlanner("task-chip")
        app, _ = make_app(planner=planner)
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        click(client, token, sid, "destination_mention", "Sa Pa")
        click(client, token, sid, "origin_mention", "Hà Nội")
        body = click(client, token, sid, "duration_days", 3).json()
        assert body["status"] == "planning" and body["plan_task_id"] == "task-chip"


# ═════════════════════════════ CHAT: khôi phục phiên ═════════════════════════════
class TestRestore:
    def test_history_roundtrip_with_chips_and_state(self):
        app, nlu = make_app(FakeNLU({"đi miền núi": {"destination_regions": ["NORTH"]}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        first = say(client, token, sid, "đi miền núi").json()
        second = click(client, token, sid, "destination_mention", "Sa Pa").json()

        # "tải lại trang": client mới, chỉ có token
        detail = TestClient(app).get(f"/api/chat/sessions/{sid}", headers=bearer(token))
        assert detail.status_code == 200
        body = detail.json()
        assert body["session_id"] == sid and body["status"] == "collecting"
        assert body["trip_request"] == second["trip_request"]

        msgs = body["messages"]
        assert [(m["role"]) for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert msgs[0]["content"] == "đi miền núi" and msgs[0]["chips"] == []
        assert msgs[1]["content"] == first["bot_message"]
        assert msgs[2]["content"] == "Sa Pa"
        assert msgs[3]["content"] == second["bot_message"]
        assert all(m["session_id"] == sid for m in msgs)

    def test_create_session_returns_current_state_of_unfinished_session(self):
        app, _ = make_app(FakeNLU({"x": {"destination": "Sa Pa"}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "x")
        resumed = client.post("/api/chat/sessions", headers=bearer(token)).json()
        assert resumed["session_id"] == sid
        assert resumed["trip_request"]["critical"]["destination_mention"] == "Sa Pa"

    def test_session_survives_logout_and_login(self):
        app, _ = make_app(FakeNLU({"x": {"destination": "Sa Pa"}}))
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        say(client, token, sid, "x")
        client.post("/api/auth/logout", headers=bearer(token))
        token2 = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["access_token"]
        assert start_session(client, token2) == sid
        assert len(client.get(f"/api/chat/sessions/{sid}", headers=bearer(token2)).json()["messages"]) == 2

    def test_corrupt_chip_payload_is_dropped_not_fatal(self):
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client)
        sid = start_session(client, token)
        cs.add_chat_message(sid, "assistant", "câu hỏi", {"chips": "không phải danh sách chip"})
        resp = client.get(f"/api/chat/sessions/{sid}", headers=bearer(token))
        assert resp.status_code == 200 and resp.json()["messages"][0]["chips"] == []


# ═════════════════════════════ Khoá phiên & đăng ký route ═════════════════════════════
class TestInternals:
    def test_same_session_same_lock_and_locks_are_bounded(self):
        assert chat_router._session_lock("abc") is chat_router._session_lock("abc")
        assert len({id(chat_router._session_lock(f"s{i}")) for i in range(5000)}) <= 64

    def test_every_chat_route_depends_on_get_current_user(self):
        """Mục 3.1 chặn ở backend: không route chat nào được quên xác thực."""
        import inspect
        for route in chat_router.router.routes:
            fn = route.endpoint if hasattr(route, "endpoint") else route.get("fn")
            if fn is None:
                continue
            defaults = [p.default for p in inspect.signature(fn).parameters.values()]
            deps = [getattr(d, "dependency", None) for d in defaults]
            assert auth_service.get_current_user in deps, f"{fn.__name__} thiếu Depends(get_current_user)"

    def test_main_app_registers_both_routers(self):
        from app.main import app as main_app
        paths = set()
        for r in main_app.routes:
            if getattr(r, "path", None):
                paths.add(r.path)
            if hasattr(r, "effective_candidates"):
                for c in r.effective_candidates():
                    if hasattr(c, "path"):
                        paths.add(c.path)
        for expected in ("/api/auth/register", "/api/auth/login", "/api/auth/me", "/api/auth/logout",
                         "/api/chat/sessions", "/api/chat/sessions/{session_id}",
                         "/api/chat/sessions/{session_id}/messages"):
            assert expected in paths, f"Missing route: {expected}"


class TestConcurrencyAndCAS:
    def test_parallel_session_creation_yields_single_session(self):
        """10 thread đồng thời gọi POST /api/chat/sessions cho cùng 1 user phải trả về cùng session_id."""
        from concurrent.futures import ThreadPoolExecutor
        app, _ = make_app()
        client = TestClient(app)
        token = signup(client, "concurrent1@example.com")
        h = bearer(token)

        def create(_):
            c = TestClient(app)
            r = c.post("/api/chat/sessions", headers=h)
            return r.status_code, r.json()["session_id"]

        with ThreadPoolExecutor(10) as ex:
            results = list(ex.map(create, range(10)))

        status_codes = [r[0] for r in results]
        session_ids = {r[1] for r in results}
        assert all(code == 200 for code in status_codes)
        assert len(session_ids) == 1, f"Tạo trùng phiên: {session_ids}"

    def test_parallel_sends_handled_cleanly_without_500(self):
        """Nhiều request gửi tin nhắn song song vào cùng một phiên: không bao giờ crash 500,
        mỗi turn thành công tăng version và ghi nhận đúng cặp tin nhắn."""
        from concurrent.futures import ThreadPoolExecutor
        app, nlu = make_app()
        client = TestClient(app)
        token = signup(client, "concurrent2@example.com")
        h = bearer(token)
        sid = start_session(client, token)
        payloads = [
            {"type": "text", "content": f"Tin nhắn số {i}"}
            for i in range(8)
        ]

        def send(idx):
            c = TestClient(app)
            return c.post(f"/api/chat/sessions/{sid}/messages", headers=h, json=payloads[idx]).status_code

        with ThreadPoolExecutor(8) as ex:
            codes = list(ex.map(send, range(8)))


        # Không có request nào bị 500 (chỉ có 200 thành công hoặc 409 conflict nếu CAS bắt được cạnh tranh)
        assert all(code in (200, 409) for code in codes), f"Mã trạng thái không mong muốn: {codes}"
        success_count = sum(1 for c in codes if c == 200)
        assert success_count >= 1

        detail = client.get(f"/api/chat/sessions/{sid}", headers=h).json()
        assert len(detail["messages"]) == 2 * success_count
        assert detail["trip_request"]["turn"] == success_count


