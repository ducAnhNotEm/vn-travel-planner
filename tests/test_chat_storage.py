"""
tests/test_chat_storage.py
===============================================================================
Kiểm thử Lát 3 - Bước 2: tầng lưu trữ app/services/chat_storage.py. PRODUCT_SPEC Mục 8.1.
Mỗi test dùng một file SQLite tạm (tmp_path) qua CHAT_DB_PATH, độc lập hoàn toàn.
Chạy: python -m pytest tests/test_chat_storage.py
"""
import json
import re
import sqlite3
import threading
from datetime import datetime
from contextlib import closing

import pytest

from app.services import chat_storage as cs


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    path = tmp_path / "chat_test.db"
    monkeypatch.setenv(cs.DB_PATH_ENV, str(path))
    return path


def make_user(email="a@b.com"):
    return cs.create_user(email, "$2b$12$fakehashfakehashfakehash")


def raw(sql, params=()):
    """Truy vấn trực tiếp file DB (không qua module) để kiểm chứng thứ thực sự được lưu."""
    with closing(sqlite3.connect(cs.get_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


# ───────────────────────────── Kết nối & schema ─────────────────────────────
class TestConnectionAndSchema:
    def test_env_var_controls_path(self, db):
        assert cs.get_db_path() == str(db)
        cs.init_db()
        assert db.exists()

    def test_default_path_when_env_missing(self, monkeypatch):
        monkeypatch.delenv(cs.DB_PATH_ENV, raising=False)
        assert cs.get_db_path() == "./chat_state.db"

    def test_memory_path_rejected(self, monkeypatch):
        monkeypatch.setenv(cs.DB_PATH_ENV, ":memory:")
        with pytest.raises(ValueError):
            cs.init_db()

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        nested = tmp_path / "x" / "y" / "chat.db"
        monkeypatch.setenv(cs.DB_PATH_ENV, str(nested))
        cs.init_db()
        assert nested.exists()

    def test_three_tables_created(self):
        cs.init_db()
        names = {r["name"] for r in raw("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"users", "chat_sessions", "chat_messages"} <= names

    @pytest.mark.parametrize("table,expected", [
        ("users", ["id", "email", "password_hash", "created_at"]),
        ("chat_sessions", ["id", "user_id", "status", "trip_request", "version", "updated_at"]),
        ("chat_messages", ["seq", "id", "session_id", "role", "content", "payload", "created_at"]),
    ])
    def test_columns(self, table, expected):
        cs.init_db()
        assert [r["name"] for r in raw(f"PRAGMA table_info({table})")] == expected


    def test_init_is_idempotent(self):
        cs.init_db()
        user = make_user()
        cs.init_db()
        cs.init_db()
        assert cs.get_user_by_id(user["id"]) is not None

    def test_wal_mode_enabled(self):
        cs.init_db()
        assert raw("PRAGMA journal_mode")[0][0].lower() == "wal"

    def test_foreign_keys_enabled_on_connection(self):
        with closing(cs._connect()) as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_db_file_recreated_if_deleted(self, db):
        make_user()
        for suffix in ("", "-wal", "-shm"):
            p = db.parent / (db.name + suffix)
            if p.exists():
                p.unlink()
        assert cs.get_user_by_email("a@b.com") is None  # DB mới, không lỗi
        make_user()


# ───────────────────────────── Users ─────────────────────────────
class TestUsers:
    def test_create_returns_dict(self):
        u = make_user()
        assert set(u) == {"id", "email", "password_hash", "created_at"}
        assert re.fullmatch(r"[0-9a-f-]{36}", u["id"])
        datetime.fromisoformat(u["created_at"])

    def test_email_stored_lowercase_and_stripped(self):
        u = cs.create_user("  Nguoi.Dung@Example.COM ", "h")
        assert u["email"] == "nguoi.dung@example.com"
        assert raw("SELECT email FROM users")[0]["email"] == "nguoi.dung@example.com"

    def test_password_hash_stored_verbatim(self):
        cs.create_user("a@b.com", "$argon2id$v=19$abc")
        assert raw("SELECT password_hash FROM users")[0][0] == "$argon2id$v=19$abc"

    def test_duplicate_email_rejected(self):
        make_user("a@b.com")
        with pytest.raises(cs.DuplicateEmailError):
            make_user("a@b.com")

    def test_duplicate_email_case_insensitive(self):
        make_user("a@b.com")
        with pytest.raises(cs.DuplicateEmailError):
            make_user("A@B.COM")
        assert len(raw("SELECT * FROM users")) == 1

    def test_duplicate_error_is_value_error(self):
        assert issubclass(cs.DuplicateEmailError, ValueError)

    @pytest.mark.parametrize("email,pw", [("", "h"), ("   ", "h"), ("a@b.com", "")])
    def test_blank_inputs_rejected(self, email, pw):
        with pytest.raises(ValueError):
            cs.create_user(email, pw)

    def test_get_by_email(self):
        u = make_user("a@b.com")
        assert cs.get_user_by_email("a@b.com") == u

    def test_get_by_email_case_and_space_insensitive(self):
        u = make_user("a@b.com")
        assert cs.get_user_by_email("  A@B.com ")["id"] == u["id"]

    def test_get_by_email_missing(self):
        assert cs.get_user_by_email("none@b.com") is None

    def test_get_by_id(self):
        u = make_user()
        assert cs.get_user_by_id(u["id"]) == u

    def test_get_by_id_missing(self):
        assert cs.get_user_by_id("does-not-exist") is None

    def test_distinct_ids(self):
        assert make_user("a@b.com")["id"] != make_user("c@d.com")["id"]

    def test_sql_injection_in_email_is_inert(self):
        make_user("a@b.com")
        assert cs.get_user_by_email("' OR 1=1 --") is None
        assert len(raw("SELECT * FROM users")) == 1


# ───────────────────────────── Sessions ─────────────────────────────
class TestSessions:
    def test_creates_new_collecting_session(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        assert s["user_id"] == u["id"]
        assert s["status"] == "collecting"
        assert isinstance(s["trip_request"], dict)
        datetime.fromisoformat(s["updated_at"])

    def test_default_trip_request_matches_spec_section_4(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        tr = s["trip_request"]
        assert tr["session_id"] == s["id"]
        assert tr["status"] == "collecting"
        assert tr["intent"] == "plan_itinerary"
        assert tr["critical"] == {"destination_mention": None, "origin_mention": None, "duration_days": None}
        assert tr["extra"]["preferences"] == [] and tr["extra"]["prefer_flight"] is None
        assert tr["hints"] == {"destination_regions": [], "terrain_types": []}
        assert tr["asked"] == [] and tr["turn"] == 0

    def test_returns_same_session_when_called_again(self):
        u = make_user()
        s1 = cs.get_or_create_active_session(u["id"])
        s2 = cs.get_or_create_active_session(u["id"])
        assert s1["id"] == s2["id"]
        assert len(raw("SELECT * FROM chat_sessions")) == 1

    def test_ready_session_counts_as_active(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        cs.update_session_trip_request(s["id"], s["trip_request"], "ready")
        assert cs.get_or_create_active_session(u["id"])["id"] == s["id"]

    @pytest.mark.parametrize("status", ["planning", "planned", "error"])
    def test_finished_session_is_not_active_so_new_one_created(self, status):
        u = make_user()
        s1 = cs.get_or_create_active_session(u["id"])
        cs.update_session_trip_request(s1["id"], s1["trip_request"], status)
        s2 = cs.get_or_create_active_session(u["id"])
        assert s2["id"] != s1["id"]
        assert s2["status"] == "collecting"
        assert cs.get_session_by_id(s1["id"])["status"] == status  # phiên cũ giữ nguyên

    def test_users_have_independent_sessions(self):
        u1, u2 = make_user("a@b.com"), make_user("c@d.com")
        s1 = cs.get_or_create_active_session(u1["id"])
        s2 = cs.get_or_create_active_session(u2["id"])
        assert s1["id"] != s2["id"]
        assert s1["user_id"] == u1["id"] and s2["user_id"] == u2["id"]

    def test_unknown_user_rejected(self):
        with pytest.raises(cs.UserNotFoundError):
            cs.get_or_create_active_session("ghost")
        assert raw("SELECT * FROM chat_sessions") == []

    def test_db_rejects_second_active_session_for_same_user(self):
        """Ràng buộc ở mức DB, không chỉ ở mức code."""
        u = make_user()
        cs.get_or_create_active_session(u["id"])
        with closing(cs._connect()) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO chat_sessions (id, user_id, status, trip_request, updated_at) "
                    "VALUES ('dup', ?, 'ready', '{}', 'x')", (u["id"],))

    def test_many_finished_sessions_allowed_alongside_one_active(self):
        u = make_user()
        for _ in range(3):
            s = cs.get_or_create_active_session(u["id"])
            cs.update_session_trip_request(s["id"], s["trip_request"], "planned")
        cs.get_or_create_active_session(u["id"])
        assert len(raw("SELECT * FROM chat_sessions WHERE user_id=?", (u["id"],))) == 4
        assert len(raw("SELECT * FROM chat_sessions WHERE user_id=? AND status IN ('collecting','ready')",
                       (u["id"],))) == 1

    def test_concurrent_calls_yield_single_active_session(self):
        u = make_user()
        ids, errors = [], []

        def worker():
            try:
                ids.append(cs.get_or_create_active_session(u["id"])["id"])
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(set(ids)) == 1
        assert len(raw("SELECT * FROM chat_sessions")) == 1

    def test_get_session_by_id(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        assert cs.get_session_by_id(s["id"]) == s

    def test_get_session_by_id_missing(self):
        assert cs.get_session_by_id("nope") is None

    def test_trip_request_stored_as_text_json(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        text = raw("SELECT trip_request FROM chat_sessions WHERE id=?", (s["id"],))[0][0]
        assert isinstance(text, str)
        assert json.loads(text) == s["trip_request"]


# ───────────────────────────── update_session_trip_request ─────────────────────────────
class TestUpdateSession:
    def _session(self):
        return cs.get_or_create_active_session(make_user()["id"])

    def test_update_with_json_string(self):
        s = self._session()
        tr = dict(s["trip_request"], status="ready")
        tr["critical"] = {"destination_mention": "Sa Pa", "origin_mention": "Hà Nội", "duration_days": 3}
        assert cs.update_session_trip_request(s["id"], json.dumps(tr), "ready") is None
        got = cs.get_session_by_id(s["id"])
        assert got["status"] == "ready"
        assert got["trip_request"]["critical"]["duration_days"] == 3

    def test_update_with_dict(self):
        s = self._session()
        tr = dict(s["trip_request"], turn=5)
        cs.update_session_trip_request(s["id"], tr, "collecting")
        assert cs.get_session_by_id(s["id"])["trip_request"]["turn"] == 5

    def test_vietnamese_text_preserved(self):
        s = self._session()
        tr = dict(s["trip_request"])
        tr["critical"] = dict(tr["critical"], destination_mention="Chùa Hương – Mỹ Đức")
        cs.update_session_trip_request(s["id"], tr, "collecting")
        assert cs.get_session_by_id(s["id"])["trip_request"]["critical"]["destination_mention"] == "Chùa Hương – Mỹ Đức"
        stored = raw("SELECT trip_request FROM chat_sessions")[0][0]
        assert "Chùa Hương" in stored  # không bị escape \uXXXX

    def test_updated_at_advances(self):
        s = self._session()
        cs.update_session_trip_request(s["id"], s["trip_request"], "ready")
        after = cs.get_session_by_id(s["id"])["updated_at"]
        assert datetime.fromisoformat(after) >= datetime.fromisoformat(s["updated_at"])
        assert after != s["updated_at"]

    def test_does_not_touch_other_sessions(self):
        s1 = cs.get_or_create_active_session(make_user("a@b.com")["id"])
        s2 = cs.get_or_create_active_session(make_user("c@d.com")["id"])
        cs.update_session_trip_request(s1["id"], dict(s1["trip_request"], turn=9), "ready")
        assert cs.get_session_by_id(s2["id"]) == s2

    @pytest.mark.parametrize("bad", ["", "ACTIVE", "done", "Collecting"])
    def test_invalid_status_rejected_and_nothing_written(self, bad):
        s = self._session()
        with pytest.raises(ValueError):
            cs.update_session_trip_request(s["id"], s["trip_request"], bad)
        assert cs.get_session_by_id(s["id"]) == s

    @pytest.mark.parametrize("status", ["collecting", "ready", "planning", "planned", "error"])
    def test_all_spec_statuses_accepted(self, status):
        s = self._session()
        cs.update_session_trip_request(s["id"], s["trip_request"], status)
        assert cs.get_session_by_id(s["id"])["status"] == status

    @pytest.mark.parametrize("bad", ["{not json", "", "[1,2]", "42", "null"])
    def test_invalid_json_rejected(self, bad):
        s = self._session()
        with pytest.raises(ValueError):
            cs.update_session_trip_request(s["id"], bad, "collecting")
        assert cs.get_session_by_id(s["id"]) == s

    def test_missing_session_raises(self):
        with pytest.raises(cs.SessionNotFoundError):
            cs.update_session_trip_request("ghost", {}, "collecting")

    def test_cannot_create_second_active_by_status_change(self):
        u = make_user()
        s1 = cs.get_or_create_active_session(u["id"])
        cs.update_session_trip_request(s1["id"], s1["trip_request"], "planned")
        s2 = cs.get_or_create_active_session(u["id"])
        with pytest.raises(sqlite3.IntegrityError):  # đưa s1 về 'collecting' khi s2 đang dở
            cs.update_session_trip_request(s1["id"], s1["trip_request"], "collecting")
        assert cs.get_or_create_active_session(u["id"])["id"] == s2["id"]


# ───────────────────────────── Messages ─────────────────────────────
class TestMessages:
    def _session(self):
        return cs.get_or_create_active_session(make_user()["id"])

    def test_add_returns_dict(self):
        s = self._session()
        m = cs.add_chat_message(s["id"], "user", "du lịch miền núi phía bắc")
        assert set(m) == {"id", "session_id", "role", "content", "payload", "created_at"}
        assert m["session_id"] == s["id"] and m["role"] == "user"
        assert m["content"] == "du lịch miền núi phía bắc"
        assert m["payload"] is None
        datetime.fromisoformat(m["created_at"])

    @pytest.mark.parametrize("role", ["user", "assistant"])
    def test_valid_roles(self, role):
        s = self._session()
        assert cs.add_chat_message(s["id"], role, "x")["role"] == role

    @pytest.mark.parametrize("role", ["system", "admin", "", "User", None])
    def test_invalid_role_rejected(self, role):
        s = self._session()
        with pytest.raises(ValueError):
            cs.add_chat_message(s["id"], role, "x")
        assert cs.get_session_messages(s["id"]) == []

    def test_non_string_content_rejected(self):
        s = self._session()
        with pytest.raises(ValueError):
            cs.add_chat_message(s["id"], "user", None)

    def test_unknown_session_rejected(self):
        with pytest.raises(cs.SessionNotFoundError):
            cs.add_chat_message("ghost", "user", "x")
        assert raw("SELECT * FROM chat_messages") == []

    def test_payload_roundtrip(self):
        s = self._session()
        payload = {"chips": [{"id": "chip_dest_sapa", "label": "Sa Pa", "slot": "destination_mention", "value": "Sa Pa"}]}
        cs.add_chat_message(s["id"], "assistant", "Quý khách muốn đi đâu?", payload)
        got = cs.get_session_messages(s["id"])[0]
        assert got["payload"] == payload

    def test_payload_none_stored_as_sql_null(self):
        s = self._session()
        cs.add_chat_message(s["id"], "user", "hi")
        assert raw("SELECT payload FROM chat_messages")[0][0] is None
        assert cs.get_session_messages(s["id"])[0]["payload"] is None

    def test_falsy_payloads_are_preserved_not_dropped(self):
        s = self._session()
        cs.add_chat_message(s["id"], "assistant", "a", {})
        cs.add_chat_message(s["id"], "assistant", "b", [])
        msgs = cs.get_session_messages(s["id"])
        assert msgs[0]["payload"] == {} and msgs[1]["payload"] == []

    def test_empty_session_has_no_messages(self):
        assert cs.get_session_messages(self._session()["id"]) == []

    def test_unknown_session_has_no_messages(self):
        assert cs.get_session_messages("ghost") == []

    def test_messages_ordered_ascending_by_created_at(self):
        s = self._session()
        for i in range(5):
            cs.add_chat_message(s["id"], "user" if i % 2 == 0 else "assistant", f"m{i}")
        msgs = cs.get_session_messages(s["id"])
        assert [m["content"] for m in msgs] == [f"m{i}" for i in range(5)]
        times = [m["created_at"] for m in msgs]
        assert times == sorted(times)

    def test_order_follows_created_at_not_insertion(self, monkeypatch):
        """Chèn sau nhưng có thời gian sớm hơn thì phải đứng trước."""
        s = self._session()
        stamps = iter(["2026-10-18T10:00:03+00:00", "2026-10-18T10:00:01+00:00", "2026-10-18T10:00:02+00:00"])
        monkeypatch.setattr(cs, "_now", lambda: next(stamps))
        for name in ("third", "first", "second"):
            cs.add_chat_message(s["id"], "user", name)
        assert [m["content"] for m in cs.get_session_messages(s["id"])] == ["first", "second", "third"]

    def test_identical_timestamps_keep_insertion_order(self, monkeypatch):
        s = self._session()
        monkeypatch.setattr(cs, "_now", lambda: "2026-10-18T10:00:00+00:00")
        for i in range(20):
            cs.add_chat_message(s["id"], "user", f"m{i}")
        assert [m["content"] for m in cs.get_session_messages(s["id"])] == [f"m{i}" for i in range(20)]

    def test_sessions_do_not_leak_messages(self):
        s1 = cs.get_or_create_active_session(make_user("a@b.com")["id"])
        s2 = cs.get_or_create_active_session(make_user("c@d.com")["id"])
        cs.add_chat_message(s1["id"], "user", "của s1")
        cs.add_chat_message(s2["id"], "user", "của s2")
        assert [m["content"] for m in cs.get_session_messages(s1["id"])] == ["của s1"]
        assert [m["content"] for m in cs.get_session_messages(s2["id"])] == ["của s2"]

    def test_vietnamese_and_quotes_preserved(self):
        s = self._session()
        text = "Tôi muốn đi 'Hội An' & \"Tràng An\"; --\n3 ngày 😀"
        cs.add_chat_message(s["id"], "user", text)
        assert cs.get_session_messages(s["id"])[0]["content"] == text

    def test_add_message_bumps_session_updated_at(self):
        s = self._session()
        cs.add_chat_message(s["id"], "user", "hi")
        assert cs.get_session_by_id(s["id"])["updated_at"] != s["updated_at"]

    def test_foreign_key_enforced_at_db_level(self):
        with closing(cs._connect()) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO chat_messages (id, session_id, role, content, created_at) "
                    "VALUES ('m', 'no-such-session', 'user', 'x', 'now')")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO chat_sessions (id, user_id, status, trip_request, updated_at) "
                    "VALUES ('s', 'no-such-user', 'collecting', '{}', 'now')")


# ───────────────────────────── Bền vững ─────────────────────────────
class TestPersistence:
    def test_data_survives_across_connections(self, db):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        cs.add_chat_message(s["id"], "user", "xin chào")
        # kết nối hoàn toàn mới (mô phỏng khởi động lại server)
        assert cs.get_user_by_email("a@b.com")["id"] == u["id"]
        assert cs.get_or_create_active_session(u["id"])["id"] == s["id"]
        assert [m["content"] for m in cs.get_session_messages(s["id"])] == ["xin chào"]

    def test_two_db_files_are_isolated(self, tmp_path, monkeypatch):
        make_user("a@b.com")
        monkeypatch.setenv(cs.DB_PATH_ENV, str(tmp_path / "other.db"))
        assert cs.get_user_by_email("a@b.com") is None


# ───────────────────────────── Auth tokens (Bước 3) ─────────────────────────────
class TestAuthTokensStorage:
    EXP = "2026-12-01T00:00:00.000000+00:00"

    def test_table_and_columns(self):
        cs.init_db()
        assert [r["name"] for r in raw("PRAGMA table_info(auth_tokens)")] == [
            "token_hash", "user_id", "created_at", "expires_at"]

    def test_save_and_get_roundtrip(self):
        u = make_user()
        assert cs.save_auth_token("h1", u["id"], self.EXP) is None
        rec = cs.get_auth_token("h1")
        assert rec["token_hash"] == "h1" and rec["user_id"] == u["id"] and rec["expires_at"] == self.EXP
        datetime.fromisoformat(rec["created_at"])

    def test_get_missing_returns_none(self):
        assert cs.get_auth_token("nope") is None

    def test_unknown_user_rejected(self):
        with pytest.raises(cs.UserNotFoundError):
            cs.save_auth_token("h1", "ghost", self.EXP)
        assert raw("SELECT * FROM auth_tokens") == []

    def test_duplicate_hash_is_not_reported_as_missing_user(self):
        u = make_user()
        cs.save_auth_token("h1", u["id"], self.EXP)
        with pytest.raises(sqlite3.IntegrityError):
            cs.save_auth_token("h1", u["id"], self.EXP)

    @pytest.mark.parametrize("h,exp", [("", "x"), ("h", "")])
    def test_blank_values_rejected(self, h, exp):
        u = make_user()
        with pytest.raises(ValueError):
            cs.save_auth_token(h, u["id"], exp)

    def test_delete_returns_bool_and_is_idempotent(self):
        u = make_user()
        cs.save_auth_token("h1", u["id"], self.EXP)
        assert cs.delete_auth_token("h1") is True
        assert cs.delete_auth_token("h1") is False
        assert cs.get_auth_token("h1") is None

    def test_delete_expired_only_removes_expired(self):
        u = make_user()
        cs.save_auth_token("old1", u["id"], "2026-01-01T00:00:00.000000+00:00")
        cs.save_auth_token("old2", u["id"], "2026-06-01T00:00:00.000000+00:00")
        cs.save_auth_token("fresh", u["id"], "2027-01-01T00:00:00.000000+00:00")
        assert cs.delete_expired_auth_tokens("2026-10-18T00:00:00.000000+00:00") == 2
        assert cs.get_auth_token("old1") is None and cs.get_auth_token("old2") is None
        assert cs.get_auth_token("fresh") is not None

    def test_delete_expired_when_nothing_expired(self):
        u = make_user()
        cs.save_auth_token("fresh", u["id"], "2027-01-01T00:00:00.000000+00:00")
        assert cs.delete_expired_auth_tokens("2026-10-18T00:00:00.000000+00:00") == 0

    def test_foreign_key_enforced_at_db_level(self):
        with closing(cs._connect()) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO auth_tokens VALUES ('h', 'no-such-user', 'now', 'later')")


# ───────────────────────────── Bước 1 Refactor: CAS & commit_turn ─────────────────────────────
class TestCommitTurnAndConcurrency:
    def _user_and_session(self):
        u = make_user()
        s = cs.get_or_create_active_session(u["id"])
        return u, s

    def test_initial_session_has_version_1(self):
        _, s = self._user_and_session()
        assert s["version"] == 1
        fetched = cs.get_session_by_id(s["id"])
        assert fetched["version"] == 1

    def test_commit_turn_atomic_success_and_bumps_version(self):
        u, s = self._user_and_session()
        trip = dict(s["trip_request"], turn=1)
        trip["critical"]["destination_mention"] = "Đà Nẵng"
        messages = [
            {"role": "user", "content": "Đi Đà Nẵng"},
            {"role": "assistant", "content": "Đi mấy ngày?", "payload": {"chips": [{"label": "3 ngày"}]}},
        ]
        updated_s, created_msgs = cs.commit_turn(
            session_id=s["id"],
            user_id=u["id"],
            expected_version=1,
            new_status="collecting",
            trip_request_json=trip,
            messages=messages,
        )
        assert updated_s["version"] == 2
        assert updated_s["trip_request"]["critical"]["destination_mention"] == "Đà Nẵng"
        assert len(created_msgs) == 2
        assert created_msgs[0]["content"] == "Đi Đà Nẵng"
        assert created_msgs[1]["payload"] == {"chips": [{"label": "3 ngày"}]}

        # Kiểm tra đọc lại từ DB
        db_msgs = cs.get_session_messages(s["id"])
        assert len(db_msgs) == 2
        assert db_msgs[0]["seq"] is not None and db_msgs[1]["seq"] is not None
        assert db_msgs[0]["seq"] < db_msgs[1]["seq"]

    def test_commit_turn_fails_on_stale_version_and_rolls_back(self):
        u, s = self._user_and_session()
        trip = dict(s["trip_request"], turn=1)
        messages = [{"role": "user", "content": "Xin chào"}]

        # Gửi với expected_version=99 (không khớp với version 1 hiện tại)
        with pytest.raises(cs.StaleSessionError) as exc_info:
            cs.commit_turn(
                session_id=s["id"],
                user_id=u["id"],
                expected_version=99,
                new_status="collecting",
                trip_request_json=trip,
                messages=messages,
            )
        assert "version hiện tại=1" in str(exc_info.value)

        # Chứng minh transaction rollback hoàn toàn: không có tin nhắn nào được ghi, version vẫn là 1
        assert cs.get_session_messages(s["id"]) == []
        assert cs.get_session_by_id(s["id"])["version"] == 1

    def test_commit_turn_rejects_wrong_user(self):
        u1, s1 = self._user_and_session()
        u2 = make_user("other@b.com")
        with pytest.raises(PermissionError):
            cs.commit_turn(
                session_id=s1["id"],
                user_id=u2["id"],  # user 2 cố tình ghi vào phiên của user 1
                expected_version=1,
                new_status="collecting",
                trip_request_json=s1["trip_request"],
                messages=[{"role": "user", "content": "hack"}],
            )
        assert cs.get_session_messages(s1["id"]) == []

    def test_get_session_for_user_and_get_session_messages_authorization(self):
        u1, s1 = self._user_and_session()
        u2 = make_user("stranger@b.com")

        # get_session_for_user
        assert cs.get_session_for_user(s1["id"], u1["id"])["id"] == s1["id"]
        assert cs.get_session_for_user(s1["id"], u2["id"]) is None

        # get_session_messages
        cs.add_chat_message(s1["id"], "user", "chào")
        assert len(cs.get_session_messages(s1["id"], user_id=u1["id"])) == 1
        with pytest.raises(PermissionError):
            cs.get_session_messages(s1["id"], user_id=u2["id"])

    def test_update_session_with_cas_version(self):
        u, s = self._user_and_session()
        # CAS đúng version
        cs.update_session_trip_request(s["id"], s["trip_request"], "ready", expected_version=1)
        updated = cs.get_session_by_id(s["id"])
        assert updated["version"] == 2
        assert updated["status"] == "ready"

        # CAS sai version ném StaleSessionError
        with pytest.raises(cs.StaleSessionError):
            cs.update_session_trip_request(s["id"], s["trip_request"], "ready", expected_version=1)

