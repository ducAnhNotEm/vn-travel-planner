"""
tests/test_chat_sessions_and_auth.py
===============================================================================
Lát 3 - Bước 5: Kiểm thử Nghiệm thu (Acceptance Tests) cho Phiên chat và Xác thực.
Tuân thủ docs/PRODUCT_SPEC.md:
  - Mục 12A: Đăng ký, đăng nhập, phân quyền, cô lập người dùng (401, 403, bảo mật mật khẩu/token)
  - Mục 12D: F5 reload, phục hồi trạng thái hội thoại, bảo tồn phiên qua đăng xuất/đăng nhập

Chạy: python -m pytest tests/test_chat_sessions_and_auth.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import chat_router
from app.services import auth_service, chat_storage as cs

PASSWORD = "matkhau-an-toan-123"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Mỗi test chạy trên một file SQLite riêng biệt, password hashing nhanh hơn."""
    db_file = str(tmp_path / "acceptance_chat_state.db")
    monkeypatch.setenv(cs.DB_PATH_ENV, db_file)
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    monkeypatch.delenv("AUTH_TOKEN_TTL_SECONDS", raising=False)
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    yield db_file


@pytest.fixture
def mock_external_deps():
    """Ghi đè NLU và Gazetteer bằng bản giả lập xác định để kiểm tra logic hội thoại."""
    nlu_calls = []

    def fake_nlu(prompt: str):
        nlu_calls.append(prompt)
        text = prompt.strip().lower()
        extracted = {"intent": "plan_itinerary"}
        if "đà nẵng" in text:
            extracted["destination"] = "Đà Nẵng"
        if "hà nội" in text:
            extracted["origin"] = "Hà Nội"
        if "3 ngày" in text:
            extracted["duration_days"] = 3
        return {"success": True, "extracted": extracted}

    class FakeGaz:
        def same_entity(self, a, b):
            return (a or "").strip().lower() == (b or "").strip().lower()

        def suggest_destinations_by_hints(self, *args, **kwargs):
            return [{"label": "Hà Giang"}, {"label": "Sa Pa"}]

    app.dependency_overrides[chat_router.get_nlu_parser] = lambda: fake_nlu
    app.dependency_overrides[chat_router.get_gazetteer] = lambda: FakeGaz()
    yield nlu_calls
    app.dependency_overrides.pop(chat_router.get_nlu_parser, None)
    app.dependency_overrides.pop(chat_router.get_gazetteer, None)


@pytest.fixture
def client():
    return TestClient(app)


def register_user(client: TestClient, email: str, password: str = PASSWORD) -> dict:
    """Helper đăng ký người dùng mới và trả về payload phản hồi."""
    resp = client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201
    return resp.json()


# =============================================================================
# MỤC 12A: XÁC THỰC, PHÂN QUYỀN VÀ CÔ LẬP NGƯỜI DÙNG (ACCEPTANCE)
# =============================================================================
class TestSection12A_AuthenticationAndAccessControl:
    """Kiểm thử nghiệm thu Tiêu chuẩn Mục 12A: Bảo mật xác thực & Cô lập đa người dùng."""

    def test_unauthenticated_requests_return_401_with_www_authenticate(self, client):
        """Mọi request chưa xác thực vào /api/chat/* phải bị chặn 401 kèm WWW-Authenticate header."""
        endpoints = [
            ("POST", "/api/chat/sessions", {}),
            ("GET", "/api/chat/sessions/any-uuid-0000", None),
            ("POST", "/api/chat/sessions/any-uuid-0000/messages", {"type": "text", "content": "alo"}),
        ]
        for method, path, json_data in endpoints:
            if method == "POST":
                res = client.post(path, json=json_data)
            else:
                res = client.get(path)
            assert res.status_code == 401, f"{method} {path} phải trả về 401"
            assert "Bearer" in res.headers.get("www-authenticate", "")
            assert res.json().get("detail") is not None

    def test_registration_and_login_lifecycle(self, client):
        """Đăng ký tạo user, tự động đăng nhập, trả Bearer token và cookie httpOnly."""
        email = "traveler_1@example.com"
        reg_res = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert reg_res.status_code == 201
        data = reg_res.json()
        token = data["access_token"]
        assert data["token_type"] == "bearer"
        assert len(token) > 20

        # Kiểm tra cookie httpOnly
        set_cookie = reg_res.headers.get("set-cookie", "")
        assert f"{auth_service.COOKIE_NAME}=" in set_cookie
        assert "HttpOnly" in set_cookie

        # Trùng email phải bị 409 Conflict
        dup_res = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert dup_res.status_code == 409

        # GET /api/auth/me qua Header Authorization
        me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["email"] == email
        assert "password" not in me_data
        assert "password_hash" not in me_data

        # Đăng xuất thu hồi token
        logout_res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout_res.status_code == 200

        # Dùng lại token cũ sau khi đăng xuất phải bị 401
        after_logout = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert after_logout.status_code == 401

    def test_multi_tenant_isolation_returns_403(self, client, mock_external_deps):
        """User B không được quyền đọc hoặc can thiệp vào phiên của User A (HTTP 403 Forbidden)."""
        # User A đăng ký & tạo phiên
        auth_a = register_user(client, "user_a@example.com")
        headers_a = {"Authorization": f"Bearer {auth_a['access_token']}"}
        ses_a_res = client.post("/api/chat/sessions", headers=headers_a)
        assert ses_a_res.status_code == 200
        session_a_id = ses_a_res.json()["session_id"]

        # User A gửi tin nhắn đầu tiên
        client.post(
            f"/api/chat/sessions/{session_a_id}/messages",
            headers=headers_a,
            json={"type": "text", "content": "Đi Đà Nẵng 3 ngày"},
        )

        # User B đăng ký
        auth_b = register_user(client, "user_b@example.com")
        headers_b = {"Authorization": f"Bearer {auth_b['access_token']}"}

        # User B cố tình đọc trộm phiên của User A -> 403 Forbidden
        get_b = client.get(f"/api/chat/sessions/{session_a_id}", headers=headers_b)
        assert get_b.status_code == 403
        assert "không có quyền" in get_b.json().get("detail", "").lower()

        # User B cố tình gửi tin nhắn văn bản vào phiên của User A -> 403 Forbidden
        post_text_b = client.post(
            f"/api/chat/sessions/{session_a_id}/messages",
            headers=headers_b,
            json={"type": "text", "content": "Hacker A"},
        )
        assert post_text_b.status_code == 403

        # User B cố tình gửi chip vào phiên của User A -> 403 Forbidden
        post_chip_b = client.post(
            f"/api/chat/sessions/{session_a_id}/messages",
            headers=headers_b,
            json={"type": "chip", "slot": "origin_mention", "value": "Hải Phòng"},
        )
        assert post_chip_b.status_code == 403

        # Kiểm tra phiên của User A vẫn toàn vẹn 100%: origin_mention vẫn là None, tin nhắn user chỉ có của A
        verify_a = client.get(f"/api/chat/sessions/{session_a_id}", headers=headers_a)
        assert verify_a.status_code == 200
        data_a = verify_a.json()
        assert data_a["trip_request"]["critical"]["origin_mention"] is None
        user_msgs = [m for m in data_a["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "Đà Nẵng" in user_msgs[0]["content"]
        assert all("Hacker" not in m["content"] for m in user_msgs)
        assert all("Hải Phòng" not in m["content"] for m in user_msgs)

    def test_nonexistent_session_returns_404(self, client):
        """Truy cập phiên không tồn tại trả về 404 (không làm lộ 403 hay crash 500)."""
        auth = register_user(client, "user_random@example.com")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        fake_id = "00000000-0000-0000-0000-000000000000"

        res_get = client.get(f"/api/chat/sessions/{fake_id}", headers=headers)
        assert res_get.status_code == 404

        res_post = client.post(
            f"/api/chat/sessions/{fake_id}/messages",
            headers=headers,
            json={"type": "text", "content": "Chào"},
        )
        assert res_post.status_code == 404


# =============================================================================
# MỤC 12D: PHỤC HỒI TRẠNG THÁI HỘI THOẠI & F5 RELOAD (ACCEPTANCE)
# =============================================================================
class TestSection12D_SessionPersistenceAndF5Reload:
    """Kiểm thử nghiệm thu Tiêu chuẩn Mục 12D: Khôi phục phiên khi reload/F5 hoặc đăng nhập lại."""

    def test_f5_reload_restores_complete_dialogue_state(self, client, mock_external_deps):
        """Mô phỏng người dùng F5 tải lại trang: Aside drawer khôi phục toàn bộ hội thoại và slot."""
        auth = register_user(client, "traveler_f5@example.com")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        # 1. Khách mở Aside drawer lần đầu -> khởi tạo phiên
        init_res = client.post("/api/chat/sessions", headers=headers)
        assert init_res.status_code == 200
        init_data = init_res.json()
        session_id = init_data["session_id"]
        assert init_data["status"] == "collecting"
        assert init_data["trip_request"]["critical"]["destination_mention"] is None

        # 2. Khách gửi tin nhắn văn bản: "Tôi muốn đi Đà Nẵng 3 ngày"
        msg_1 = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            headers=headers,
            json={"type": "text", "content": "Tôi muốn đi Đà Nẵng 3 ngày"},
        )
        assert msg_1.status_code == 200
        data_1 = msg_1.json()
        # NLU trích xuất destination="Đà Nẵng", duration_days=3 -> hệ thống hỏi origin
        req_1 = data_1["trip_request"]["critical"]
        assert req_1["destination_mention"] == "Đà Nẵng"
        assert req_1["duration_days"] == 3
        assert req_1["origin_mention"] is None
        assert data_1["status"] == "collecting"
        assert len(data_1["chips"]) > 0  # Có chip gợi ý điểm xuất phát

        # 3. Khách bấm chọn chip: Điểm xuất phát = "Hà Nội" (bypasses NLU)
        msg_2 = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            headers=headers,
            json={"type": "chip", "slot": "origin_mention", "value": "Hà Nội"},
        )
        assert msg_2.status_code == 200
        data_2 = msg_2.json()
        req_2 = data_2["trip_request"]["critical"]
        assert req_2["origin_mention"] == "Hà Nội"
        assert req_2["destination_mention"] == "Đà Nẵng"
        assert req_2["duration_days"] == 3
        # Đã đủ 3 slot cốt lõi: destination, origin, duration -> trạng thái sẵn sàng (ready)
        assert data_2["status"] == "ready"

        # 4. GIẢ LẬP F5 RELOAD TRÌNH DUYỆT (Kịch bản 1: Gọi GET /api/chat/sessions/{id})
        f5_get = client.get(f"/api/chat/sessions/{session_id}", headers=headers)
        assert f5_get.status_code == 200
        restored_state = f5_get.json()
        assert restored_state["session_id"] == session_id
        assert restored_state["status"] == "ready"
        assert restored_state["trip_request"]["critical"]["destination_mention"] == "Đà Nẵng"
        assert restored_state["trip_request"]["critical"]["origin_mention"] == "Hà Nội"
        assert restored_state["trip_request"]["critical"]["duration_days"] == 3

        # Lịch sử tin nhắn được khôi phục nguyên vẹn và đúng thứ tự thời gian
        msgs = restored_state["messages"]
        assert len(msgs) >= 3
        assert msgs[0]["role"] == "user"
        assert "Đà Nẵng" in msgs[0]["content"]
        assert msgs[1]["role"] == "assistant"
        # Tin nhắn sự kiện chip của user được hiển thị tự nhiên
        assert msgs[2]["role"] == "user"
        assert "Hà Nội" in msgs[2]["content"]

        # 5. GIẢ LẬP MỞ LẠI ASIDE DRAWER (Kịch bản 2: Gọi POST /api/chat/sessions)
        # Theo Mục 8.1: Mỗi user chỉ có tối đa 1 phiên đang dở -> phải trả lại đúng phiên này
        reopen_res = client.post("/api/chat/sessions", headers=headers)
        assert reopen_res.status_code == 200
        reopen_data = reopen_res.json()
        assert reopen_data["session_id"] == session_id
        assert reopen_data["status"] == "ready"
        assert reopen_data["trip_request"]["critical"]["destination_mention"] == "Đà Nẵng"

    def test_session_survives_browser_close_and_relogin(self, client, mock_external_deps):
        """Khách đăng xuất, tắt trình duyệt, sau đó đăng nhập lại -> phiên cũ vẫn được phục hồi."""
        email = "persisted_user@example.com"
        auth = register_user(client, email)
        headers_first = {"Authorization": f"Bearer {auth['access_token']}"}

        # Khách trò chuyện dở
        ses_res = client.post("/api/chat/sessions", headers=headers_first)
        session_id = ses_res.json()["session_id"]
        client.post(
            f"/api/chat/sessions/{session_id}/messages",
            headers=headers_first,
            json={"type": "text", "content": "Muốn đi Đà Nẵng"},
        )

        # Khách đăng xuất
        logout = client.post("/api/auth/logout", headers=headers_first)
        assert logout.status_code == 200

        # Khách đăng nhập lại -> cấp token mới
        login_res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert login_res.status_code == 200
        new_token = login_res.json()["access_token"]
        headers_second = {"Authorization": f"Bearer {new_token}"}

        # Mở Aside drawer -> khôi phục đúng phiên đang dở với dữ liệu cũ
        restore_res = client.post("/api/chat/sessions", headers=headers_second)
        assert restore_res.status_code == 200
        restored = restore_res.json()
        assert restored["session_id"] == session_id
        assert restored["trip_request"]["critical"]["destination_mention"] == "Đà Nẵng"

    def test_new_session_created_only_after_previous_completed_or_planning(self, client, mock_external_deps):
        """Khi phiên trước đã chuyển sang 'planning' (lên lịch xong), lần mở drawer kế tiếp tạo phiên mới."""
        auth = register_user(client, "planner_user@example.com")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        # Giả lập planner được kích hoạt
        def mock_planner(req, user_id):
            return "plan-task-xyz-999"

        app.dependency_overrides[chat_router.get_plan_starter] = lambda: mock_planner

        try:
            # Tạo phiên 1
            s1_res = client.post("/api/chat/sessions", headers=headers)
            s1_id = s1_res.json()["session_id"]

            # Gửi thông tin đủ để kích hoạt planner: Đà Nẵng, Hà Nội, 3 ngày
            client.post(f"/api/chat/sessions/{s1_id}/messages", headers=headers, json={"type": "text", "content": "Đi Đà Nẵng 3 ngày"})
            final_res = client.post(
                f"/api/chat/sessions/{s1_id}/messages",
                headers=headers,
                json={"type": "chip", "slot": "origin_mention", "value": "Hà Nội"},
            )
            assert final_res.status_code == 200
            assert final_res.json()["status"] == "planning"
            assert final_res.json()["plan_task_id"] == "plan-task-xyz-999"

            # Vì phiên 1 đã sang 'planning', mở Aside drawer tiếp theo (POST /api/chat/sessions) PHẢI tạo phiên 2 mới
            s2_res = client.post("/api/chat/sessions", headers=headers)
            assert s2_res.status_code == 200
            s2_data = s2_res.json()
            assert s2_data["session_id"] != s1_id
            assert s2_data["status"] == "collecting"
            assert s2_data["trip_request"]["critical"]["destination_mention"] is None
        finally:
            app.dependency_overrides.pop(chat_router.get_plan_starter, None)

    def test_f5_cookie_only_session_restoration(self, client, mock_external_deps):
        """Khách đăng ký/đăng nhập và dùng duy nhất cookie (không header Authorization).
        Giả lập F5 tải lại trang: GET /api/chat/sessions/{id} chỉ qua cookie httpOnly
        phải khôi phục đầy đủ phiên và lịch sử hội thoại."""
        email = "cookie_f5_user@example.com"
        reg_res = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        assert reg_res.status_code == 201
        assert "access_token" in client.cookies

        # Tạo phiên chỉ bằng cookie (không gửi Authorization header)
        s_res = client.post("/api/chat/sessions")
        assert s_res.status_code == 200
        session_id = s_res.json()["session_id"]

        # Gửi tin nhắn đầu tiên bằng cookie
        msg_res = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"type": "text", "content": "Đi Đà Nẵng 3 ngày"},
        )
        assert msg_res.status_code == 200

        # GIẢ LẬP F5 RELOAD CHỈ DÙNG COOKIE:
        f5_res = client.get(f"/api/chat/sessions/{session_id}")
        assert f5_res.status_code == 200
        f5_data = f5_res.json()
        assert f5_data["session_id"] == session_id
        assert f5_data["trip_request"]["critical"]["destination_mention"] == "Đà Nẵng"
        assert f5_data["trip_request"]["critical"]["duration_days"] == 3
        assert len(f5_data["messages"]) >= 2

        # Gửi thêm tin nhắn bằng cookie
        reply_res = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"type": "chip", "slot": "origin_mention", "value": "Hà Nội"},
        )
        assert reply_res.status_code == 200
        assert reply_res.json()["trip_request"]["critical"]["origin_mention"] == "Hà Nội"

        # Đăng xuất bằng cookie
        logout_res = client.post("/api/auth/logout")
        assert logout_res.status_code == 200

        # Sau khi đăng xuất, gọi lại bị 401
        after_logout = client.get(f"/api/chat/sessions/{session_id}")
        assert after_logout.status_code == 401
