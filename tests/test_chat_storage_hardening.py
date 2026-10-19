"""
tests/test_chat_storage_hardening.py
===============================================================================
Kiểm thử các lỗi đã sửa ở tầng lưu trữ (mã review trong ngoặc):
  CAS song song (A1) · rollback giữa chừng (A2) · migration + init dở dang (N1/N2) · JSON hỏng (N4)
  phân quyền bắt buộc (N5/C1) · hợp đồng & máy trạng thái (N6) · status một nguồn (A5) · thứ tự theo seq (A6)
Chạy: python -m pytest tests/test_chat_storage_hardening.py -v
"""
import json
import sqlite3
import threading
from contextlib import closing

import pytest

from app.services import chat_storage as cs


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    path = tmp_path / "hardening.db"
    monkeypatch.setenv(cs.DB_PATH_ENV, str(path))
    return path


def make_user(email="a@b.com"):
    return cs.create_user(email, "hash")


def new_session(email="a@b.com"):
    u = make_user(email)
    return u, cs.get_or_create_active_session(u["id"])


def raw(sql, params=()):
    with closing(sqlite3.connect(cs.get_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def run_threads(n, target):
    threads = [threading.Thread(target=target, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ───────────────────────────── A1: CAS song song ─────────────────────────────
class TestParallelCAS:
    def test_only_one_of_eight_commits_wins(self):
        u, s = new_session()
        results = []

        def worker(i):
            try:
                cs.commit_turn(s["id"], u["id"], 1, "collecting", s["trip_request"],
                               [{"role": "user", "content": f"u{i}"}, {"role": "assistant", "content": f"b{i}"}])
                results.append("ok")
            except cs.StaleSessionError:
                results.append("stale")
            except Exception as exc:  # pragma: no cover
                results.append(f"ERR {type(exc).__name__}: {exc}")

        run_threads(8, worker)
        assert sorted(results) == ["ok"] + ["stale"] * 7
        assert len(cs.list_messages_unscoped(s["id"])) == 2          # chỉ lượt thắng được ghi
        assert cs.get_session_by_id(s["id"])["version"] == 2

    def test_sequential_retry_after_stale_succeeds(self):
        u, s = new_session()
        cs.commit_turn(s["id"], u["id"], 1, "collecting", s["trip_request"], [])
        with pytest.raises(cs.StaleSessionError):
            cs.commit_turn(s["id"], u["id"], 1, "collecting", s["trip_request"], [])
        fresh = cs.get_session_for_user(s["id"], u["id"])
        cs.commit_turn(s["id"], u["id"], fresh["version"], "collecting", fresh["trip_request"], [])
        assert cs.get_session_by_id(s["id"])["version"] == 3

    def test_concurrent_create_user_sessions_unique_per_user(self):
        users = [make_user(f"u{i}@b.com") for i in range(4)]
        ids = {}

        def worker(i):
            u = users[i % 4]
            ids.setdefault(u["id"], set()).add(cs.get_or_create_active_session(u["id"])["id"])

        run_threads(16, worker)
        assert all(len(v) == 1 for v in ids.values())
        assert len(raw("SELECT * FROM chat_sessions")) == 4


# ───────────────────────────── A2: nguyên tử ─────────────────────────────
class TestAtomicity:
    def test_failure_inserting_second_message_rolls_back_state_and_first_message(self):
        u, s = new_session()
        trip = dict(s["trip_request"], turn=7)
        with pytest.raises(sqlite3.IntegrityError):  # id tin nhắn trùng -> lỗi ở tin nhắn thứ hai
            cs.commit_turn(s["id"], u["id"], 1, "ready", trip,
                           [{"id": "X", "role": "user", "content": "a"}, {"id": "X", "role": "assistant", "content": "b"}])
        after = cs.get_session_by_id(s["id"])
        assert after["version"] == 1 and after["status"] == "collecting" and after["trip_request"]["turn"] == 0
        assert cs.list_messages_unscoped(s["id"]) == []

    @pytest.mark.parametrize("bad_messages", [
        [{"role": "system", "content": "x"}],
        [{"role": "user", "content": None}],
    ])
    def test_invalid_message_writes_nothing(self, bad_messages):
        u, s = new_session()
        with pytest.raises(ValueError):
            cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], bad_messages)
        assert cs.get_session_by_id(s["id"])["version"] == 1

    def test_missing_session_and_wrong_user(self):
        u, s = new_session()
        other = make_user("o@b.com")
        with pytest.raises(cs.SessionNotFoundError):
            cs.commit_turn("ghost", u["id"], 1, "ready", {}, [])
        with pytest.raises(PermissionError):
            cs.commit_turn(s["id"], other["id"], 1, "ready", s["trip_request"], [{"role": "user", "content": "x"}])
        assert cs.list_messages_unscoped(s["id"]) == []

    def test_returned_session_is_the_committed_one(self):
        u, s = new_session()
        updated, created = cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"],
                                          [{"role": "user", "content": "x", "payload": {"k": 1}}])
        assert updated["version"] == 2 and updated["status"] == "ready"
        assert created[0]["payload"] == {"k": 1}

    def test_payload_survives_roundtrip_and_order_is_insertion(self):
        u, s = new_session()
        cs.commit_turn(s["id"], u["id"], 1, "collecting", s["trip_request"],
                       [{"role": "user", "content": "1"}, {"role": "assistant", "content": "2", "payload": {"chips": []}}])
        msgs = cs.get_session_messages(s["id"], u["id"])
        assert [m["content"] for m in msgs] == ["1", "2"]
        assert msgs[0]["seq"] < msgs[1]["seq"] and msgs[1]["payload"] == {"chips": []}


# ───────────────────────────── Máy trạng thái ─────────────────────────────
class TestStateMachine:
    def test_commit_turn_rejects_illegal_transition(self):
        u, s = new_session()
        with pytest.raises(cs.InvalidTransitionError):
            cs.commit_turn(s["id"], u["id"], 1, "planned", s["trip_request"], [])
        assert cs.get_session_by_id(s["id"])["version"] == 1

    def test_finished_sessions_are_terminal(self):
        u, s = new_session()
        v = cs.update_session_trip_request(s["id"], s["trip_request"], "planned")
        with pytest.raises(cs.InvalidTransitionError):
            cs.commit_turn(s["id"], u["id"], v, "collecting", s["trip_request"], [])

    def test_planning_to_ready_allowed_for_compensation(self):
        u, s = new_session()
        v1 = cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], [])[0]["version"]
        v2 = cs.commit_turn(s["id"], u["id"], v1, "planning", s["trip_request"], [])[0]["version"]
        assert cs.commit_turn(s["id"], u["id"], v2, "ready", s["trip_request"], [])[0]["status"] == "ready"

    def test_transition_session_status_is_cas_on_status(self):
        u, s = new_session()
        v = cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], [])[0]["version"]
        cs.commit_turn(s["id"], u["id"], v, "planning", s["trip_request"], [])
        assert cs.transition_session_status(s["id"], "planning", "planned") is True
        # worker thứ hai (hoặc router chậm chân) không được ghi đè kết quả đã có
        assert cs.transition_session_status(s["id"], "planning", "error") is False
        assert cs.get_session_by_id(s["id"])["status"] == "planned"

    def test_transition_session_status_validates(self):
        _, s = new_session()
        with pytest.raises(cs.InvalidTransitionError):
            cs.transition_session_status(s["id"], "collecting", "planned")
        with pytest.raises(cs.SessionNotFoundError):
            cs.transition_session_status("ghost", "planning", "planned")
        with pytest.raises(ValueError):
            cs.transition_session_status(s["id"], "collecting", "bogus")

    def test_router_commit_after_worker_finished_is_stale_not_overwrite(self):
        """Kịch bản A1: worker xong (planned) trước khi router kịp ghi -> router nhận Stale, KHÔNG ghi đè."""
        u, s = new_session()
        v = cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], [])[0]
        v_plan = cs.commit_turn(s["id"], u["id"], v["version"], "planning", s["trip_request"], [])[0]["version"]
        assert cs.transition_session_status(s["id"], "planning", "planned")
        with pytest.raises(cs.StaleSessionError):
            cs.commit_turn(s["id"], u["id"], v_plan, "ready", s["trip_request"], [{"role": "assistant", "content": "x"}])
        assert cs.get_session_by_id(s["id"])["status"] == "planned"


# ───────────────────────────── A5: status một nguồn ─────────────────────────────
class TestSingleSourceOfStatus:
    def test_json_status_is_forced_to_match_column_on_write(self):
        u, s = new_session()
        updated, _ = cs.commit_turn(s["id"], u["id"], 1, "ready", dict(s["trip_request"], status="collecting"), [])
        assert updated["status"] == "ready" and updated["trip_request"]["status"] == "ready"
        stored = json.loads(raw("SELECT trip_request FROM chat_sessions")[0][0])
        assert stored["status"] == "ready"

    def test_read_overlays_column_even_if_stored_json_diverges(self):
        _, s = new_session()
        with closing(sqlite3.connect(cs.get_db_path())) as conn:
            conn.execute("UPDATE chat_sessions SET status='ready'")  # lệch cố ý: JSON vẫn 'collecting'
            conn.commit()
        assert cs.get_session_by_id(s["id"])["trip_request"]["status"] == "ready"

    def test_transition_keeps_json_mirror_in_sync(self):
        u, s = new_session()
        v = cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], [])[0]["version"]
        cs.commit_turn(s["id"], u["id"], v, "planning", s["trip_request"], [])
        cs.transition_session_status(s["id"], "planning", "planned")
        assert json.loads(raw("SELECT trip_request FROM chat_sessions")[0][0])["status"] == "planned"


# ───────────────────────────── A6: thứ tự theo seq ─────────────────────────────
class TestOrdering:
    def test_backward_clock_does_not_reorder(self, monkeypatch):
        u, s = new_session()
        stamps = iter(["2026-10-18T10:00:05+00:00", "2026-10-18T10:00:01+00:00"])
        monkeypatch.setattr(cs, "_now", lambda: next(stamps))
        cs.add_chat_message(s["id"], "user", "gửi trước")
        cs.add_chat_message(s["id"], "assistant", "gửi sau")
        assert [m["content"] for m in cs.get_session_messages(s["id"], u["id"])] == ["gửi trước", "gửi sau"]

    def test_seq_is_never_reused(self):
        _, s = new_session()
        a = cs.add_chat_message(s["id"], "user", "a")
        seq_a = cs.list_messages_unscoped(s["id"])[0]["seq"]
        with closing(sqlite3.connect(cs.get_db_path())) as conn:
            conn.execute("DELETE FROM chat_messages WHERE id=?", (a["id"],))
            conn.commit()
        cs.add_chat_message(s["id"], "user", "b")
        assert cs.list_messages_unscoped(s["id"])[0]["seq"] > seq_a


# ───────────────────────────── N1/N2: migration ─────────────────────────────
LEGACY_V2_SCHEMA = """
CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE chat_sessions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
    trip_request TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX uq_chat_sessions_one_active_per_user ON chat_sessions(user_id) WHERE status IN ('collecting','ready');
CREATE TABLE chat_messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id),
    role TEXT NOT NULL, content TEXT NOT NULL, payload TEXT, created_at TEXT NOT NULL);
CREATE INDEX idx_chat_messages_session ON chat_messages(session_id, created_at);
CREATE TABLE auth_tokens (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
"""


def seed_legacy(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(LEGACY_V2_SCHEMA)
        conn.execute("INSERT INTO users VALUES ('u1','a@b.com','h','2026-01-01T00:00:00+00:00')")
        conn.execute("INSERT INTO chat_sessions VALUES ('s1','u1','collecting',?, '2026-01-01T00:00:00+00:00')",
                     (json.dumps({"session_id": "s1", "status": "collecting", "turn": 2}),))
        # chèn lệch thứ tự thời gian để kiểm tra thứ tự được giữ theo (created_at, rowid) của bản cũ
        conn.execute("INSERT INTO chat_messages VALUES ('m2','s1','assistant','hai',NULL,'2026-01-01T00:00:02+00:00')")
        conn.execute("INSERT INTO chat_messages VALUES ('m1','s1','user','một',NULL,'2026-01-01T00:00:01+00:00')")
        conn.execute("INSERT INTO auth_tokens VALUES ('th','u1','2026-01-01T00:00:00+00:00','2999-01-01T00:00:00+00:00')")
        conn.commit()


class TestMigration:
    def test_fresh_db_gets_current_schema_version(self):
        cs.init_db()
        assert raw("PRAGMA user_version")[0][0] == cs.SCHEMA_VERSION

    def test_legacy_step2_db_is_upgraded_and_data_preserved(self, db):
        seed_legacy(str(db))
        s = cs.get_session_by_id("s1")
        assert s["version"] == 1 and s["trip_request"]["turn"] == 2
        msgs = cs.get_session_messages("s1", "u1")
        assert [m["content"] for m in msgs] == ["một", "hai"]            # giữ thứ tự cũ theo created_at
        assert [m["seq"] for m in msgs] == sorted(m["seq"] for m in msgs)
        assert cs.get_auth_token("th") is not None
        assert cs.get_user_by_email("a@b.com")["id"] == "u1"
        names = {r["name"] for r in raw("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "chat_messages_legacy" not in names

    def test_legacy_db_works_end_to_end_after_upgrade(self, db):
        seed_legacy(str(db))
        s = cs.get_session_for_user("s1", "u1")
        updated, created = cs.commit_turn("s1", "u1", s["version"], "ready", s["trip_request"],
                                          [{"role": "user", "content": "mới"}])
        assert updated["version"] == 2 and created[0]["content"] == "mới"
        assert [m["content"] for m in cs.get_session_messages("s1", "u1")] == ["một", "hai", "mới"]

    def test_legacy_unique_active_index_still_enforced(self, db):
        seed_legacy(str(db))
        cs.init_db()
        with closing(cs._connect()) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO chat_sessions (id,user_id,status,trip_request,updated_at) "
                             "VALUES ('dup','u1','ready','{}','x')")

    def test_partial_init_with_only_users_table_is_repaired(self, db):
        with closing(sqlite3.connect(str(db))) as conn:
            conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
                         "password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.commit()
        u = make_user()
        assert cs.get_or_create_active_session(u["id"])["status"] == "collecting"

    def test_step1_db_with_seq_but_no_user_version_is_adopted(self, db):
        """DB do bản Bước 1 cũ tạo (đã có version/seq nhưng user_version=0) vẫn được nhận mà không mất dữ liệu."""
        cs.init_db()
        u, s = new_session()
        cs.add_chat_message(s["id"], "user", "giữ lại")
        with closing(sqlite3.connect(str(db))) as conn:
            conn.execute("PRAGMA user_version = 0")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at)")
            conn.commit()
        assert [m["content"] for m in cs.get_session_messages(s["id"], u["id"])] == ["giữ lại"]
        assert raw("PRAGMA user_version")[0][0] == cs.SCHEMA_VERSION
        idx = {r["name"] for r in raw("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_chat_messages_session" not in idx

    def test_failed_migration_rolls_back_completely(self, db, monkeypatch):
        seed_legacy(str(db))

        def boom(conn):
            conn.execute("ALTER TABLE chat_messages RENAME TO chat_messages_legacy")  # bước đầu đã chạy
            raise RuntimeError("boom")

        real_apply = cs._apply_schema
        monkeypatch.setattr(cs, "_apply_schema", boom)
        with pytest.raises(RuntimeError):
            cs.init_db()
        monkeypatch.setattr(cs, "_apply_schema", real_apply)  # KHÔNG dùng undo(): nó hoàn tác cả CHAT_DB_PATH
        names = {r["name"] for r in raw("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "chat_messages" in names and "chat_messages_legacy" not in names  # không để lại schema nửa vời
        assert raw("PRAGMA user_version")[0][0] == 0
        assert cs.get_session_by_id("s1")["version"] == 1                       # lần sau migrate lại bình thường

    def test_newer_db_is_refused(self, db):
        cs.init_db()
        with closing(sqlite3.connect(str(db))) as conn:
            conn.execute(f"PRAGMA user_version = {cs.SCHEMA_VERSION + 1}")
            conn.commit()
        with pytest.raises(RuntimeError):
            cs.get_user_by_email("a@b.com")

    def test_concurrent_cold_start_is_safe(self, db):
        errors = []

        def worker(i):
            try:
                cs.init_db()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        run_threads(8, worker)
        assert not errors and raw("PRAGMA user_version")[0][0] == cs.SCHEMA_VERSION


# ───────────────────────────── N4: JSON hỏng ─────────────────────────────
class TestCorruptTripRequest:
    def _corrupt(self, session_id, text="{broken"):
        with closing(sqlite3.connect(cs.get_db_path())) as conn:
            conn.execute("UPDATE chat_sessions SET trip_request=? WHERE id=?", (text, session_id))
            conn.commit()

    @pytest.mark.parametrize("bad", ["{broken", "[1,2]", "42", "null", ""])
    def test_reads_do_not_raise_and_flag_corrupt(self, bad):
        u, s = new_session()
        self._corrupt(s["id"], bad)
        for got in (cs.get_session_by_id(s["id"]), cs.get_session_for_user(s["id"], u["id"]),
                    cs.get_or_create_active_session(u["id"])):
            assert got["corrupt"] is True and got["trip_request"] is None and got["id"] == s["id"]

    def test_healthy_session_is_not_flagged(self):
        _, s = new_session()
        assert s["corrupt"] is False

    def test_quarantine_frees_the_slot_and_preserves_raw_data(self):
        u, s = new_session()
        self._corrupt(s["id"])
        assert cs.quarantine_session(s["id"], u["id"]) is True
        assert cs.get_session_by_id(s["id"])["status"] == "error"
        assert raw("SELECT trip_request FROM chat_sessions WHERE id=?", (s["id"],))[0][0] == "{broken"
        fresh = cs.get_or_create_active_session(u["id"])
        assert fresh["id"] != s["id"] and fresh["corrupt"] is False

    def test_quarantine_only_touches_own_active_sessions(self):
        u, s = new_session()
        other = make_user("o@b.com")
        assert cs.quarantine_session(s["id"], other["id"]) is False
        assert cs.get_session_by_id(s["id"])["status"] == "collecting"
        cs.quarantine_session(s["id"], u["id"])
        assert cs.quarantine_session(s["id"], u["id"]) is False  # đã 'error' -> không đổi nữa

    def test_corrupt_payload_only_drops_chips(self):
        _, s = new_session()
        cs.add_chat_message(s["id"], "assistant", "hi", {"chips": []})
        with closing(sqlite3.connect(cs.get_db_path())) as conn:
            conn.execute("UPDATE chat_messages SET payload='{bad'")
            conn.commit()
        msg = cs.list_messages_unscoped(s["id"])[0]
        assert msg["content"] == "hi" and msg["payload"] is None


# ───────────────────────────── C1/N5: phân quyền ─────────────────────────────
class TestAuthorizationIsMandatory:
    def test_scoped_reads_hide_foreign_data(self):
        u1, s1 = new_session("a@b.com")
        u2 = make_user("c@d.com")
        cs.add_chat_message(s1["id"], "user", "bí mật")
        assert cs.get_session_for_user(s1["id"], u2["id"]) is None
        assert cs.get_session_messages(s1["id"], u2["id"]) == []
        assert len(cs.get_session_messages(s1["id"], u1["id"])) == 1

    @pytest.mark.parametrize("falsy_user", ["", "nobody"])
    def test_empty_or_unknown_user_id_never_matches(self, falsy_user):
        """N5: user_id rỗng không được rơi về nhánh không lọc."""
        u, s = new_session()
        cs.add_chat_message(s["id"], "user", "x")
        assert cs.get_session_for_user(s["id"], falsy_user) is None
        assert cs.get_session_messages(s["id"], falsy_user) == []

    def test_user_id_is_a_required_argument(self):
        _, s = new_session()
        with pytest.raises(TypeError):
            cs.get_session_messages(s["id"])
        with pytest.raises(TypeError):
            cs.get_session_for_user(s["id"])

    def test_get_session_owner_exposes_only_the_owner_id(self):
        u, s = new_session()
        assert cs.get_session_owner(s["id"]) == u["id"]
        assert cs.get_session_owner("ghost") is None

    def test_cas_update_requires_user_id_and_checks_ownership(self):
        u, s = new_session()
        other = make_user("o@b.com")
        with pytest.raises(ValueError):
            cs.update_session_trip_request(s["id"], s["trip_request"], "ready", expected_version=1)
        with pytest.raises(PermissionError):
            cs.update_session_trip_request(s["id"], s["trip_request"], "ready", expected_version=1, user_id=other["id"])
        assert cs.get_session_by_id(s["id"])["version"] == 1


# ───────────────────────────── N6: hợp đồng ─────────────────────────────
class TestContracts:
    def test_update_returns_new_version_in_both_modes(self):
        u, s = new_session()
        assert cs.update_session_trip_request(s["id"], s["trip_request"], "collecting") == 2
        assert cs.update_session_trip_request(s["id"], s["trip_request"], "collecting",
                                              expected_version=2, user_id=u["id"]) == 3

    def test_lock_timeout_surfaces_as_operational_error(self, monkeypatch):
        monkeypatch.setattr(cs, "DB_TIMEOUT_SECONDS", 0.2)
        u, s = new_session()
        blocker = sqlite3.connect(cs.get_db_path(), isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(sqlite3.OperationalError):
                cs.commit_turn(s["id"], u["id"], 1, "ready", s["trip_request"], [])
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
        assert cs.get_session_by_id(s["id"])["version"] == 1
