"""
tests/test_auth_service.py
===============================================================================
Kiểm thử Lát 3 - Bước 3: app/services/auth_service.py. PRODUCT_SPEC Mục 3.1, 3.2.
Mỗi test dùng một file SQLite tạm (tmp_path) và số vòng lặp PBKDF2 thấp để chạy nhanh.
Chạy: python -m pytest tests/test_auth_service.py
"""
import base64
import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.chat_models import MIN_PASSWORD_LENGTH
from app.services import auth_service as auth
from app.services import chat_storage as cs

PASSWORD = "matkhau-hop-le-123"
EMAIL = "nguoi.dung@example.com"
FIXED_NOW = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(cs.DB_PATH_ENV, str(tmp_path / "auth_test.db"))
    monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "1000")
    monkeypatch.delenv("AUTH_TOKEN_TTL_SECONDS", raising=False)
    return tmp_path


def request(authorization=None, cookie=None):
    """Request giả: chỉ cần .headers và .cookies (dependency chỉ đọc hai thứ này)."""
    headers = {} if authorization is None else {"authorization": authorization}
    cookies = {} if cookie is None else {auth.COOKIE_NAME: cookie}
    return SimpleNamespace(headers=headers, cookies=cookies)


def expect_401(fn, *args, **kwargs):
    with pytest.raises(auth.HTTPException) as info:
        fn(*args, **kwargs)
    exc = info.value
    assert exc.status_code == 401
    assert exc.headers == {"WWW-Authenticate": "Bearer"}
    return exc


def login(email=EMAIL, password=PASSWORD):
    auth.register_user(email, password)
    return auth.authenticate_user(email, password)


def raw(sql, params=()):
    cs.init_db()  # đảm bảo file + bảng tồn tại ngay cả khi chưa có thao tác nào chạm vào DB
    with closing(sqlite3.connect(cs.get_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


# ───────────────────────────── Băm mật khẩu ─────────────────────────────
class TestPasswordHashing:
    def test_correct_password_verifies(self):
        assert auth.verify_password(PASSWORD, auth.hash_password(PASSWORD)) is True

    def test_wrong_password_rejected(self):
        assert auth.verify_password("sai-mat-khau", auth.hash_password(PASSWORD)) is False

    def test_empty_password_rejected(self):
        assert auth.verify_password("", auth.hash_password(PASSWORD)) is False

    def test_case_sensitive(self):
        assert auth.verify_password(PASSWORD.upper(), auth.hash_password(PASSWORD)) is False

    def test_whitespace_is_significant(self):
        h = auth.hash_password("abc 12345")
        assert auth.verify_password("abc 12345", h)
        assert not auth.verify_password("abc 12345 ", h)
        assert not auth.verify_password(" abc 12345", h)

    def test_vietnamese_unicode_password(self):
        h = auth.hash_password("Mật-khẩu-Tiếng-Việt-😀")
        assert auth.verify_password("Mật-khẩu-Tiếng-Việt-😀", h)
        assert not auth.verify_password("Mat-khau-Tieng-Viet-😀", h)

    def test_max_length_password(self):
        pw = "p" * 128
        assert auth.verify_password(pw, auth.hash_password(pw))

    def test_format_is_self_describing(self):
        algo, iters, salt, digest = auth.hash_password(PASSWORD).split("$")
        assert algo == "pbkdf2_sha256" and iters == "1000"
        assert len(base64.b64decode(salt)) == 16 and len(base64.b64decode(digest)) == 32

    def test_plaintext_not_in_hash(self):
        assert PASSWORD not in auth.hash_password(PASSWORD)

    def test_random_salt_makes_hashes_differ(self):
        assert auth.hash_password(PASSWORD) != auth.hash_password(PASSWORD)

    def test_interoperable_with_plain_hashlib(self):
        """Hash dựng tay bằng hashlib chuẩn phải verify được (không phụ thuộc định dạng ngầm)."""
        salt = b"0123456789abcdef"
        digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, 5000)
        stored = "pbkdf2_sha256$5000$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())
        assert auth.verify_password(PASSWORD, stored)
        assert not auth.verify_password("khac", stored)

    def test_verify_uses_iterations_stored_in_hash(self, monkeypatch):
        h = auth.hash_password(PASSWORD)  # 1000 vòng
        monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", "2000")
        assert auth.verify_password(PASSWORD, h)  # mật khẩu cũ vẫn dùng được sau khi đổi cấu hình
        assert auth.hash_password(PASSWORD).split("$")[1] == "2000"

    def test_tampered_digest_rejected(self):
        algo, iters, salt, digest = auth.hash_password(PASSWORD).split("$")
        raw_digest = bytearray(base64.b64decode(digest))
        raw_digest[0] ^= 0x01
        bad = "$".join((algo, iters, salt, base64.b64encode(bytes(raw_digest)).decode()))
        assert not auth.verify_password(PASSWORD, bad)

    @pytest.mark.parametrize("bad_hash", [
        "", "abc", "a$b$c$d", "pbkdf2_sha256$1000$salt", "pbkdf2_sha256$x$AAAA$AAAA",
        "pbkdf2_sha256$0$AAAA$AAAA", "pbkdf2_sha256$-5$AAAA$AAAA",
        "pbkdf2_sha256$999999999999$AAAA$AAAA",          # số vòng lặp khổng lồ: không được treo máy
        "pbkdf2_sha256$1000$!!!notbase64$AAAA", "bcrypt$1000$AAAA$AAAA",
        "pbkdf2_sha256$1000$AAAA$AAAA$extra", None, 123, b"bytes",
    ])
    def test_malformed_stored_hash_returns_false_never_raises(self, bad_hash):
        assert auth.verify_password(PASSWORD, bad_hash) is False

    @pytest.mark.parametrize("bad_password", [None, 123, b"bytes", ["x"]])
    def test_non_string_password_verify_false(self, bad_password):
        assert auth.verify_password(bad_password, auth.hash_password(PASSWORD)) is False

    @pytest.mark.parametrize("bad_password", ["", None, 123, b"bytes"])
    def test_hash_rejects_empty_or_non_string(self, bad_password):
        with pytest.raises(ValueError):
            auth.hash_password(bad_password)

    @pytest.mark.parametrize("bad", ["abc", "0", "-1", ""])
    def test_invalid_iteration_config(self, bad, monkeypatch):
        monkeypatch.setenv("PASSWORD_HASH_ITERATIONS", bad)
        if bad == "":
            assert auth.hash_password(PASSWORD).split("$")[1] == str(auth.DEFAULT_ITERATIONS)
        else:
            with pytest.raises(ValueError):
                auth.hash_password(PASSWORD)


# ───────────────────────────── Đăng ký ─────────────────────────────
class TestRegister:
    def test_success_returns_user_out(self):
        user = auth.register_user(EMAIL, PASSWORD)
        assert user.email == EMAIL
        assert re.fullmatch(r"[0-9a-f-]{36}", user.id)
        datetime.fromisoformat(user.created_at)

    def test_response_has_no_password_data(self):
        user = auth.register_user(EMAIL, PASSWORD)
        dumped = str(user.model_dump())
        assert "password" not in dumped and PASSWORD not in dumped

    def test_user_persisted_with_hash_not_plaintext(self):
        auth.register_user(EMAIL, PASSWORD)
        row = cs.get_user_by_email(EMAIL)
        assert row["password_hash"] != PASSWORD and PASSWORD not in row["password_hash"]
        assert auth.verify_password(PASSWORD, row["password_hash"])

    def test_email_normalized_to_lowercase(self):
        user = auth.register_user("  Nguoi.Dung@EXAMPLE.com ", PASSWORD)
        assert user.email == EMAIL
        assert cs.get_user_by_email(EMAIL) is not None

    def test_duplicate_email_blocked_with_409(self):
        auth.register_user(EMAIL, PASSWORD)
        with pytest.raises(auth.HTTPException) as info:
            auth.register_user(EMAIL, "mat-khau-khac-456")
        assert info.value.status_code == 409
        assert len(raw("SELECT * FROM users")) == 1

    def test_duplicate_email_case_insensitive(self):
        auth.register_user(EMAIL, PASSWORD)
        with pytest.raises(auth.HTTPException) as info:
            auth.register_user(EMAIL.upper(), PASSWORD)
        assert info.value.status_code == 409

    def test_duplicate_does_not_change_original_password(self):
        auth.register_user(EMAIL, PASSWORD)
        with pytest.raises(auth.HTTPException):
            auth.register_user(EMAIL, "mat-khau-ke-tan-cong")
        assert auth.authenticate_user(EMAIL, PASSWORD).user.email == EMAIL
        expect_401(auth.authenticate_user, EMAIL, "mat-khau-ke-tan-cong")

    @pytest.mark.parametrize("bad_email", ["", "khong-co-a-cong", "a@b", "a@@b.com", "a b@c.com", ".a@b.com"])
    def test_invalid_email_rejected(self, bad_email):
        with pytest.raises(ValueError):
            auth.register_user(bad_email, PASSWORD)
        assert raw("SELECT * FROM users") == []

    def test_short_password_rejected(self):
        with pytest.raises(ValueError):
            auth.register_user(EMAIL, "x" * (MIN_PASSWORD_LENGTH - 1))
        assert raw("SELECT * FROM users") == []

    def test_minimum_length_password_accepted(self):
        pw = "x" * MIN_PASSWORD_LENGTH
        auth.register_user(EMAIL, pw)
        assert auth.authenticate_user(EMAIL, pw).user.email == EMAIL

    def test_two_users_independent(self):
        a = auth.register_user("a@b.com", PASSWORD)
        b = auth.register_user("c@d.com", "mat-khau-thu-hai")
        assert a.id != b.id
        expect_401(auth.authenticate_user, "a@b.com", "mat-khau-thu-hai")

    def test_register_and_login_returns_working_token(self):
        result = auth.register_and_login(EMAIL, PASSWORD)
        assert result.token_type == "bearer" and result.user.email == EMAIL
        assert auth.get_user_from_token(result.access_token).id == result.user.id


# ───────────────────────────── Đăng nhập ─────────────────────────────
class TestAuthenticate:
    def test_correct_credentials_return_token_response(self):
        auth.register_user(EMAIL, PASSWORD)
        result = auth.authenticate_user(EMAIL, PASSWORD)
        assert result.token_type == "bearer"
        assert result.access_token
        assert result.user.email == EMAIL
        assert "password" not in str(result.model_dump())

    def test_email_case_and_space_insensitive(self):
        auth.register_user(EMAIL, PASSWORD)
        assert auth.authenticate_user("  NGUOI.DUNG@Example.COM ", PASSWORD).user.email == EMAIL

    def test_wrong_password_401_generic_message(self):
        auth.register_user(EMAIL, PASSWORD)
        exc = expect_401(auth.authenticate_user, EMAIL, "sai-mat-khau")
        assert exc.detail == "email hoặc mật khẩu không đúng"

    def test_unknown_email_401_same_message_as_wrong_password(self):
        auth.register_user(EMAIL, PASSWORD)
        wrong_pw = expect_401(auth.authenticate_user, EMAIL, "sai-mat-khau")
        unknown = expect_401(auth.authenticate_user, "khong-co@example.com", PASSWORD)
        assert unknown.detail == wrong_pw.detail  # không lộ email có tồn tại hay không

    @pytest.mark.parametrize("password", ["", " ", PASSWORD + " ", PASSWORD.upper()])
    def test_bad_passwords_rejected(self, password):
        auth.register_user(EMAIL, PASSWORD)
        expect_401(auth.authenticate_user, EMAIL, password)

    def test_failed_login_issues_no_token(self):
        auth.register_user(EMAIL, PASSWORD)
        expect_401(auth.authenticate_user, EMAIL, "sai-mat-khau")
        assert raw("SELECT * FROM auth_tokens") == []

    def test_unknown_email_still_performs_one_hash(self, monkeypatch):
        """Giảm lộ email qua độ trễ: email lạ vẫn tốn đúng một lần băm như email có thật."""
        auth.register_user(EMAIL, PASSWORD)
        calls = []
        real = hashlib.pbkdf2_hmac

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(auth.hashlib, "pbkdf2_hmac", counting)
        expect_401(auth.authenticate_user, "khong-co@example.com", PASSWORD)
        unknown_calls = len(calls)
        calls.clear()
        expect_401(auth.authenticate_user, EMAIL, "sai-mat-khau")
        assert unknown_calls == len(calls) == 1

    def test_each_login_gets_distinct_token_and_all_stay_valid(self):
        auth.register_user(EMAIL, PASSWORD)
        t1 = auth.authenticate_user(EMAIL, PASSWORD).access_token
        t2 = auth.authenticate_user(EMAIL, PASSWORD).access_token
        assert t1 != t2
        assert auth.get_user_from_token(t1).email == auth.get_user_from_token(t2).email == EMAIL

    def test_non_string_inputs_rejected_with_401(self):
        auth.register_user(EMAIL, PASSWORD)
        expect_401(auth.authenticate_user, None, PASSWORD)
        expect_401(auth.authenticate_user, EMAIL, None)

    def test_sql_injection_attempt_is_just_a_wrong_login(self):
        auth.register_user(EMAIL, PASSWORD)
        expect_401(auth.authenticate_user, "' OR 1=1 --", PASSWORD)
        expect_401(auth.authenticate_user, EMAIL, "' OR '1'='1")


# ───────────────────────────── Token ─────────────────────────────
class TestTokens:
    def test_token_is_long_unique_urlsafe(self):
        user = auth.register_user(EMAIL, PASSWORD)
        tokens = {auth.issue_token(user.id) for _ in range(50)}
        assert len(tokens) == 50
        for t in tokens:
            assert len(t) >= 40 and re.fullmatch(r"[A-Za-z0-9_-]+", t)

    def test_only_hash_of_token_is_stored(self):
        token = login().access_token
        stored = raw("SELECT * FROM auth_tokens")
        assert len(stored) == 1
        assert token not in tuple(stored[0])
        assert stored[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()

    def test_default_ttl_is_30_days(self, monkeypatch):
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        user = auth.register_user(EMAIL, PASSWORD)
        token = auth.issue_token(user.id)
        rec = cs.get_auth_token(hashlib.sha256(token.encode()).hexdigest())
        assert datetime.fromisoformat(rec["expires_at"]) == FIXED_NOW + timedelta(days=30)

    def test_ttl_configurable(self, monkeypatch):
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")
        user = auth.register_user(EMAIL, PASSWORD)
        token = auth.issue_token(user.id)
        rec = cs.get_auth_token(hashlib.sha256(token.encode()).hexdigest())
        assert datetime.fromisoformat(rec["expires_at"]) == FIXED_NOW + timedelta(hours=1)

    def test_valid_before_expiry(self, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        token = login().access_token
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW + timedelta(seconds=3599))
        assert auth.get_user_from_token(token).email == EMAIL

    @pytest.mark.parametrize("seconds_later", [3600, 3601, 86400 * 365])
    def test_invalid_at_and_after_expiry(self, seconds_later, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        token = login().access_token
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW + timedelta(seconds=seconds_later))
        expect_401(auth.get_user_from_token, token)

    def test_expired_token_is_deleted_on_use(self, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "60")
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        token = login().access_token
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW + timedelta(minutes=5))
        expect_401(auth.get_user_from_token, token)
        assert raw("SELECT * FROM auth_tokens") == []

    def test_expired_tokens_purged_when_new_token_issued(self, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "60")
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        user = auth.register_user(EMAIL, PASSWORD)
        for _ in range(3):
            auth.issue_token(user.id)
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW + timedelta(minutes=5))
        fresh = auth.issue_token(user.id)
        rows = raw("SELECT * FROM auth_tokens")
        assert len(rows) == 1 and rows[0]["token_hash"] == hashlib.sha256(fresh.encode()).hexdigest()

    def test_revoke_invalidates_token(self):
        token = login().access_token
        auth.revoke_token(token)
        expect_401(auth.get_user_from_token, token)

    def test_revoke_returns_none(self):
        assert auth.revoke_token(login().access_token) is None

    def test_revoke_is_idempotent(self):
        token = login().access_token
        auth.revoke_token(token)
        auth.revoke_token(token)

    @pytest.mark.parametrize("junk", [None, "", "token-khong-ton-tai", 123])
    def test_revoke_junk_does_not_raise(self, junk):
        auth.revoke_token(junk)

    def test_revoke_only_affects_that_token(self):
        auth.register_user(EMAIL, PASSWORD)
        t1 = auth.authenticate_user(EMAIL, PASSWORD).access_token
        t2 = auth.authenticate_user(EMAIL, PASSWORD).access_token
        auth.revoke_token(t1)
        expect_401(auth.get_user_from_token, t1)
        assert auth.get_user_from_token(t2).email == EMAIL

    def test_token_of_deleted_user_rejected(self):
        token = login().access_token
        with closing(sqlite3.connect(cs.get_db_path())) as conn:
            with conn:
                conn.execute("DELETE FROM users")
        expect_401(auth.get_user_from_token, token)
        assert raw("SELECT * FROM auth_tokens") == []

    def test_tokens_do_not_cross_users(self):
        a = auth.register_and_login("a@b.com", PASSWORD)
        b = auth.register_and_login("c@d.com", PASSWORD)
        assert auth.get_user_from_token(a.access_token).email == "a@b.com"
        assert auth.get_user_from_token(b.access_token).email == "c@d.com"

    @pytest.mark.parametrize("bad", [None, "", "abc", "Bearer xyz", "😀", "' OR 1=1 --", 123, b"bytes"])
    def test_garbage_tokens_rejected(self, bad):
        login()
        expect_401(auth.get_user_from_token, bad)

    def test_tampered_token_rejected(self):
        token = login().access_token
        flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
        expect_401(auth.get_user_from_token, flipped)
        assert auth.get_user_from_token(token).email == EMAIL


# ───────────────────────────── extract_token ─────────────────────────────
class TestExtractToken:
    @pytest.mark.parametrize("header,cookie,expected", [
        ("Bearer abc", None, "abc"),
        ("bearer abc", None, "abc"),
        ("BEARER   abc  ", None, "abc"),
        ("Bearer", None, None),
        ("Bearer ", None, None),
        ("Basic abc", None, None),
        ("abc", None, None),
        (None, None, None),
        ("", "", None),
        (None, "ck", "ck"),
        ("Bearer h", "ck", "h"),
        ("Basic x", "ck", "ck"),
        ("Bearer", "ck", "ck"),
        (None, "   ", None),
    ])
    def test_extract(self, header, cookie, expected):
        assert auth.extract_token(header, cookie) == expected


# ───────────────────────────── get_current_user ─────────────────────────────
class TestGetCurrentUser:
    def test_valid_bearer_token_returns_correct_user(self):
        result = login()
        user = auth.get_current_user(request(authorization=f"Bearer {result.access_token}"))
        assert user.id == result.user.id and user.email == EMAIL

    def test_valid_cookie_token_returns_correct_user(self):
        result = login()
        assert auth.get_current_user(request(cookie=result.access_token)).id == result.user.id

    def test_correct_user_among_several(self):
        a = auth.register_and_login("a@b.com", PASSWORD)
        b = auth.register_and_login("c@d.com", PASSWORD)
        assert auth.get_current_user(request(f"Bearer {b.access_token}")).email == "c@d.com"
        assert auth.get_current_user(request(f"Bearer {a.access_token}")).email == "a@b.com"

    def test_result_has_no_password_hash(self):
        result = login()
        user = auth.get_current_user(request(f"Bearer {result.access_token}"))
        assert "password" not in str(user.model_dump())

    def test_header_takes_precedence_over_cookie(self):
        a = auth.register_and_login("a@b.com", PASSWORD)
        b = auth.register_and_login("c@d.com", PASSWORD)
        user = auth.get_current_user(request(f"Bearer {a.access_token}", cookie=b.access_token))
        assert user.email == "a@b.com"

    def test_invalid_bearer_is_not_rescued_by_valid_cookie(self):
        """Thông tin đăng nhập tường minh trong header mà sai thì từ chối, không lén dùng cookie."""
        good = login()
        expect_401(auth.get_current_user, request("Bearer sai-token", cookie=good.access_token))

    def test_no_credentials_401_not_authenticated(self):
        exc = expect_401(auth.get_current_user, request())
        assert exc.detail == auth.NOT_AUTHENTICATED_DETAIL

    @pytest.mark.parametrize("header", ["", "Bearer", "Bearer ", "   ", "Basic dXNlcjpwYXNz", "token-tran-khong-scheme"])
    def test_empty_or_malformed_header_401(self, header):
        login()
        expect_401(auth.get_current_user, request(authorization=header))

    def test_empty_cookie_401(self):
        expect_401(auth.get_current_user, request(cookie=""))

    def test_unknown_token_401(self):
        login()
        exc = expect_401(auth.get_current_user, request("Bearer khong-ton-tai"))
        assert exc.detail == auth.INVALID_TOKEN_DETAIL

    def test_expired_token_401(self, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "60")
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW)
        token = login().access_token
        monkeypatch.setattr(auth, "_utcnow", lambda: FIXED_NOW + timedelta(hours=1))
        expect_401(auth.get_current_user, request(f"Bearer {token}"))

    def test_revoked_token_401_after_logout(self):
        token = login().access_token
        req = request(f"Bearer {token}")
        assert auth.get_current_user(req).email == EMAIL
        auth.revoke_token(token)
        expect_401(auth.get_current_user, req)

    def test_token_from_other_database_rejected(self, tmp_path, monkeypatch):
        token = login().access_token
        monkeypatch.setenv(cs.DB_PATH_ENV, str(tmp_path / "another.db"))
        expect_401(auth.get_current_user, request(f"Bearer {token}"))


# ───────────────────────────── Ghép với FastAPI thật ─────────────────────────────
class TestFastAPIIntegration:
    """Cần fastapi + httpx (TestClient); thiếu thì tự bỏ qua."""

    def _client(self):
        pytest.importorskip("httpx")
        testclient = pytest.importorskip("fastapi.testclient")
        from fastapi import Depends, FastAPI

        app = FastAPI()

        @app.get("/protected")
        def protected(user=Depends(auth.get_current_user)):
            return {"email": user.email}

        return testclient.TestClient(app)

    def test_unauthenticated_gets_401_with_www_authenticate(self):
        client = self._client()
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    def test_bearer_header_grants_access(self):
        client = self._client()
        token = login().access_token
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200 and resp.json() == {"email": EMAIL}

    def test_cookie_grants_access(self):
        client = self._client()
        client.cookies.set(auth.COOKIE_NAME, login().access_token)
        resp = client.get("/protected")
        assert resp.status_code == 200 and resp.json() == {"email": EMAIL}

    def test_invalid_token_401(self):
        client = self._client()
        assert client.get("/protected", headers={"Authorization": "Bearer sai"}).status_code == 401

    def test_revoked_token_401(self):
        client = self._client()
        token = login().access_token
        auth.revoke_token(token)
        assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 401
