"""
tests/test_dialogue_engine.py
===============================================================================
Kiểm thử Lát 2: hỏi làm rõ + nút gợi ý (PRODUCT_SPEC Mục 3, 4, 6, 7, 10).

Lớp TestAcceptance12B ở cuối file bám sát từng câu Given/Then của Mục 12B (Hỏi lại và chip).
Các lớp còn lại phủ thêm Mục 3, 4, 6, 7, 10.

Gazetteer dùng một travel_db.db GIẢ dựng trong tmp_path (không phụ thuộc DB thật): đủ bảng provinces/places.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from app.dialogue_models import (
    ChipItem,
    ClarificationQuestion,
    ClarificationTurn,
    TripRequest,
)
from app.services import dialogue_engine as eng
from app.services.dialogue_engine import (
    apply_chip_event,
    check_missing_slots,
    generate_clarification_turn,
    load_dialogue_config,
    record_turn,
)
from app.services.dialogue_state import merge_nlu_slots
from app.services.gazetteer import (
    DESTINATION_CATALOG,
    LEAF_REGIONS,
    TERRAIN_TYPES,
    Gazetteer,
    rank_destinations,
)

PROVINCE_NAMES = {
    1: "Thành phố Hà Nội", 4: "Tỉnh Cao Bằng", 8: "Tỉnh Tuyên Quang", 11: "Tỉnh Điện Biên", 14: "Tỉnh Sơn La",
    15: "Tỉnh Lào Cai", 19: "Tỉnh Thái Nguyên", 20: "Tỉnh Lạng Sơn", 22: "Tỉnh Quảng Ninh", 25: "Tỉnh Phú Thọ",
    31: "Thành phố Hải Phòng", 37: "Tỉnh Ninh Bình", 38: "Tỉnh Thanh Hóa", 44: "Tỉnh Quảng Trị", 46: "Thành phố Huế",
    48: "Thành phố Đà Nẵng", 51: "Tỉnh Quảng Ngãi", 52: "Tỉnh Gia Lai", 56: "Tỉnh Khánh Hòa", 66: "Tỉnh Đắk Lắk",
    68: "Tỉnh Lâm Đồng", 79: "Thành phố Hồ Chí Minh", 80: "Tỉnh Tây Ninh", 86: "Tỉnh Vĩnh Long",
    91: "Tỉnh An Giang", 92: "Thành phố Cần Thơ", 96: "Tỉnh Cà Mau", 40: "Tỉnh Nghệ An",
}


@pytest.fixture(scope="module")
def gaz(tmp_path_factory):
    db = tmp_path_factory.mktemp("gaz") / "travel_db.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE provinces (code INTEGER PRIMARY KEY, name TEXT, codename TEXT)")
    conn.execute("CREATE TABLE places (id INTEGER PRIMARY KEY, name TEXT, province_code INTEGER)")
    conn.executemany(
        "INSERT INTO provinces VALUES (?, ?, ?)",
        [(c, n, n.lower().replace(" ", "_")) for c, n in PROVINCE_NAMES.items()],
    )
    # Điểm tham quan cụ thể (Mục 10: chùa Hương thuộc Hà Nội nhưng KHÔNG phải "Hà Nội")
    conn.executemany("INSERT INTO places VALUES (?, ?, ?)", [(1, "Chùa Hương", 1), (2, "Hồ Hoàn Kiếm", 1)])
    conn.commit()
    conn.close()
    return Gazetteer(str(db))


def req(**kw) -> TripRequest:
    """Dựng TripRequest nhanh: req(dest="Sa Pa", origin="Hà Nội", days=3, regions=[...], terrains=[...], excluded=[...])"""
    r = TripRequest()
    r.critical.destination_mention = kw.get("dest")
    r.critical.origin_mention = kw.get("origin")
    r.critical.duration_days = kw.get("days")
    r.hints.destination_regions = list(kw.get("regions", []))
    r.hints.terrain_types = list(kw.get("terrains", []))
    r.extra.excluded_mentions = list(kw.get("excluded", []))
    return r


def labels(chips):
    return [c.label for c in chips]


# ═══════════════════════════════════════════════════════════════════════════════
# Config (Mục 6)
# ═══════════════════════════════════════════════════════════════════════════════
class TestConfig:
    def test_file_matches_spec_section_6(self):
        cfg = load_dialogue_config()
        assert cfg["max_questions_per_turn"] == 2
        assert [s["slot"] for s in cfg["critical_slots"]] == ["destination_mention", "origin_mention", "duration_days"]
        assert "{region_suffix}" in cfg["critical_slots"][0]["ask"]
        assert cfg["critical_slots"][0]["suggest"] == {"source": "gazetteer_by_hints", "limit": 6}
        assert cfg["critical_slots"][1]["suggest"] == {
            "source": "popular_origins", "include_current_location": True, "limit": 5}
        assert cfg["critical_slots"][2]["suggest"] == {"source": "static", "values": [1, 2, 3, 4, 5]}
        assert cfg["extra_slots"] == [
            {"slot": "group_size", "default": 2}, {"slot": "budget_total_vnd", "default": None}]
        assert cfg["after_ready"] == "auto_plan"

    @pytest.mark.parametrize("mutate", [
        lambda c: c.update(max_questions_per_turn=0),
        lambda c: c.update(critical_slots=[]),
        lambda c: c["critical_slots"][0].update(slot="budget_total_vnd"),   # không phải slot quan trọng
        lambda c: c["critical_slots"][1].update(slot="destination_mention"),  # trùng slot
        lambda c: c["critical_slots"][0]["suggest"].update(source="bịa_ra"),
        lambda c: c["critical_slots"][2]["suggest"].update(values=[]),
        lambda c: c["critical_slots"][0].update(ask="  "),
    ])
    def test_invalid_config_is_rejected(self, mutate):
        cfg = load_dialogue_config()
        mutate(cfg)
        with pytest.raises(ValueError):
            eng.validate_config(cfg)

    def test_load_from_custom_path(self, tmp_path):
        p = tmp_path / "d.json"
        p.write_text(json.dumps(load_dialogue_config()), encoding="utf-8")
        assert load_dialogue_config(p)["max_questions_per_turn"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# check_missing_slots (Mục 4.2, 4.3)
# ═══════════════════════════════════════════════════════════════════════════════
class TestCheckMissingSlots:
    def test_empty_request_misses_all_three_in_config_order(self):
        assert check_missing_slots(TripRequest()) == ["destination_mention", "origin_mention", "duration_days"]

    def test_region_and_terrain_hints_do_not_count_as_destination(self):
        r = req(regions=["mien_bac"], terrains=["nui"], origin="Hà Nội", days=3)  # "miền núi phía bắc"
        assert check_missing_slots(r) == ["destination_mention"]

    def test_all_critical_filled(self):
        assert check_missing_slots(req(dest="Sa Pa", origin="Hà Nội", days=3)) == []

    def test_current_location_counts_as_origin(self):
        assert check_missing_slots(req(dest="Sa Pa", origin="CURRENT_LOCATION", days=2)) == []

    @pytest.mark.parametrize("field,value,missing", [
        ("dest", "   ", "destination_mention"),
        ("origin", "", "origin_mention"),
        ("days", 0, "duration_days"),
    ])
    def test_blank_or_invalid_values_are_missing(self, field, value, missing):
        base = dict(dest="Sa Pa", origin="Hà Nội", days=3)
        base[field] = value
        assert check_missing_slots(req(**base)) == [missing]

    def test_extra_slots_never_block(self):
        r = req(dest="Sa Pa", origin="Hà Nội", days=3)
        assert r.extra.group_size is None and r.extra.budget_total_vnd is None
        assert check_missing_slots(r) == []

    def test_defaulted_critical_slot_is_not_missing(self):
        r = req(dest="Sa Pa", origin="Hà Nội", days=3)
        r.defaulted = ["duration_days"]
        assert check_missing_slots(r) == []

    def test_does_not_mutate_request(self):
        r = req(regions=["mien_bac"])
        before = r.model_dump()
        check_missing_slots(r)
        assert r.model_dump() == before


# ═══════════════════════════════════════════════════════════════════════════════
# generate_clarification_turn (Mục 3, 6, 10)
# ═══════════════════════════════════════════════════════════════════════════════
class TestClarificationTurn:
    def test_max_two_questions_even_with_three_missing(self, gaz):
        t = generate_clarification_turn(TripRequest(), gaz)
        assert t.status == "collecting"
        assert [q.slot for q in t.questions] == ["destination_mention", "origin_mention"]
        assert t.missing_slots == ["destination_mention", "origin_mention", "duration_days"]  # đủ 3, không bị cắt

    def test_one_and_two_missing(self, gaz):
        t1 = generate_clarification_turn(req(dest="Sa Pa", origin="Hà Nội"), gaz)
        assert [q.slot for q in t1.questions] == ["duration_days"]
        t2 = generate_clarification_turn(req(dest="Sa Pa"), gaz)
        assert [q.slot for q in t2.questions] == ["origin_mention", "duration_days"]

    def test_ready_when_all_critical_present(self, gaz):
        t = generate_clarification_turn(req(dest="Sa Pa", origin="Hà Nội", days=3), gaz)
        assert t.status == "ready" and t.questions == [] and t.missing_slots == [] and t.chips == []
        assert t.next_action == "auto_plan"

    def test_max_questions_comes_from_config(self, gaz):
        cfg = load_dialogue_config()
        cfg["max_questions_per_turn"] = 1
        assert len(generate_clarification_turn(TripRequest(), gaz, cfg).questions) == 1
        cfg["max_questions_per_turn"] = 3
        assert len(generate_clarification_turn(TripRequest(), gaz, cfg).questions) == 3

    def test_question_text_comes_from_config(self, gaz):
        cfg = load_dialogue_config()
        cfg["critical_slots"][2]["ask"] = "Đi mấy hôm?"
        t = generate_clarification_turn(req(dest="Sa Pa", origin="Hà Nội"), gaz, cfg)
        assert t.questions[0].text == "Đi mấy hôm?"

    def test_does_not_mutate_request(self, gaz):
        r = req(regions=["mien_bac"], terrains=["nui"])
        before = r.model_dump()
        generate_clarification_turn(r, gaz)
        assert r.model_dump() == before

    # ── câu hỏi điểm đến + chip theo hints ──────────────────────────────────────
    def test_destination_question_mentions_region_and_terrain(self, gaz):
        t = generate_clarification_turn(req(regions=["mien_bac"], terrains=["nui"]), gaz)
        q = t.questions[0]
        assert q.text == "Quý khách muốn đi điểm cụ thể nào ở miền Bắc (địa hình núi)?"
        assert "{" not in q.text

    def test_destination_question_without_hints_has_clean_text(self, gaz):
        q = generate_clarification_turn(TripRequest(), gaz).questions[0]
        assert q.text == "Quý khách muốn đi điểm cụ thể nào?"

    def test_northern_mountains_chips(self, gaz):
        q = generate_clarification_turn(req(regions=["mien_bac"], terrains=["nui"]), gaz).questions[0]
        assert labels(q.chips) == ["Sa Pa", "Hà Giang", "Mộc Châu", "Mù Cang Chải", "Mai Châu", "Điện Biên"]
        assert all(c.slot == "destination_mention" for c in q.chips)
        assert all(c.value == c.label for c in q.chips)
        assert len(q.chips) <= 6

    def test_chip_matches_spec_example_shape(self, gaz):
        sapa = generate_clarification_turn(req(regions=["tay_bac"]), gaz).questions[0].chips[0]
        assert sapa == ChipItem(id="chip_dest_sapa", label="Sa Pa", slot="destination_mention", value="Sa Pa")

    def test_beach_hint_gives_coastal_places_not_mountains(self, gaz):
        chips = generate_clarification_turn(req(terrains=["bien"]), gaz).questions[0].chips
        assert chips and "Phú Quốc" in labels(chips) and "Sa Pa" not in labels(chips)

    def test_no_hints_gives_popular_destinations(self, gaz):
        chips = generate_clarification_turn(TripRequest(), gaz).questions[0].chips
        assert labels(chips) == ["Đà Nẵng", "Phú Quốc", "Đà Lạt", "Hạ Long", "Nha Trang", "Sa Pa"]

    def test_chips_are_stable_between_calls(self, gaz):
        r = req(regions=["mien_trung"])
        a = generate_clarification_turn(r, gaz).model_dump()
        b = generate_clarification_turn(r, gaz).model_dump()
        assert a == b

    def test_chip_ids_and_labels_unique_within_a_turn(self, gaz):
        t = generate_clarification_turn(TripRequest(), gaz)
        ids = [c.id for c in t.chips]
        assert len(ids) == len(set(ids))

    def test_excluded_mentions_are_not_suggested(self, gaz):
        r = req(regions=["tay_bac"], excluded=["sapa"])  # không dấu, viết liền
        assert "Sa Pa" not in labels(generate_clarification_turn(r, gaz).questions[0].chips)

    def test_excluding_a_province_excludes_places_inside_it(self, gaz):
        r = req(regions=["tay_bac"], excluded=["Lào Cai"])  # Sa Pa, Mù Cang Chải thuộc Lào Cai (mã 15)
        got = labels(generate_clarification_turn(r, gaz).questions[0].chips)
        assert "Sa Pa" not in got and "Mù Cang Chải" not in got and "Mộc Châu" in got

    def test_destination_chips_avoid_the_origin(self, gaz):
        got = labels(generate_clarification_turn(req(origin="Hà Nội", terrains=["dong_bang"]), gaz).questions[0].chips)
        assert "Hà Nội" not in got and "Ninh Bình" in got

    def test_origin_da_nang_does_not_hide_hoi_an(self, gaz):
        # xuất phát Đà Nẵng vẫn được gợi ý đi Hội An (cùng mã tỉnh 48 nhưng khác thực thể)
        got = labels(generate_clarification_turn(req(origin="Đà Nẵng", regions=["nam_trung_bo"]), gaz).questions[0].chips)
        assert "Hội An" in got and "Đà Nẵng" not in got

    # ── chip điểm xuất phát / số ngày ───────────────────────────────────────────
    def test_origin_chips(self, gaz):
        q = generate_clarification_turn(req(dest="Sa Pa"), gaz).questions[0]
        assert q.slot == "origin_mention"
        assert q.chips[0] == ChipItem(
            id="chip_orig_currentlocation", label="Vị trí hiện tại", slot="origin_mention", value="CURRENT_LOCATION")
        assert labels(q.chips) == ["Vị trí hiện tại", "Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Hải Phòng"]
        assert len(q.chips) <= 5

    def test_origin_chips_skip_the_destination_entity(self, gaz):
        q = generate_clarification_turn(req(dest="Sài Gòn"), gaz).questions[0]  # = TP.HCM
        assert "TP. Hồ Chí Minh" not in labels(q.chips) and "Hà Nội" in labels(q.chips)

    def test_origin_chips_can_omit_current_location_by_config(self, gaz):
        cfg = load_dialogue_config()
        cfg["critical_slots"][1]["suggest"]["include_current_location"] = False
        q = generate_clarification_turn(req(dest="Sa Pa"), gaz, cfg).questions[0]
        assert "Vị trí hiện tại" not in labels(q.chips)

    def test_duration_chips_are_1_to_5_integers(self, gaz):
        q = generate_clarification_turn(req(dest="Sa Pa", origin="Hà Nội"), gaz).questions[0]
        assert [c.value for c in q.chips] == [1, 2, 3, 4, 5]
        assert all(isinstance(c.value, int) and not isinstance(c.value, bool) for c in q.chips)
        assert labels(q.chips) == ["1 ngày", "2 ngày", "3 ngày", "4 ngày", "5 ngày"]
        assert q.chips[2].id == "chip_dur_3"

    def test_flat_chip_row_follows_question_order_and_is_serialised(self, gaz):
        t = generate_clarification_turn(TripRequest(), gaz)
        assert [c.slot for c in t.chips][0] == "destination_mention"
        assert [c.slot for c in t.chips][-1] == "origin_mention"
        assert len(t.model_dump()["chips"]) == len(t.chips)

    # ── điểm đến trùng điểm xuất phát (Mục 10) ──────────────────────────────────
    def test_same_destination_and_origin_asks_again(self, gaz):
        t = generate_clarification_turn(req(dest="Hà Nội", origin="Hà Nội", days=2), gaz)
        assert t.status == "collecting" and t.missing_slots == []
        q = t.questions[0]
        assert (q.slot, q.reason) == ("destination_mention", "conflict")
        assert "trùng" in q.text and "Hà Nội" in q.text
        assert "Hà Nội" not in labels(q.chips) and q.chips

    @pytest.mark.parametrize("dest,origin", [("TP.HCM", "Sài Gòn"), ("ha noi", "Hà Nội"), ("HN", "Hà Nội")])
    def test_equivalent_names_conflict(self, gaz, dest, origin):
        t = generate_clarification_turn(req(dest=dest, origin=origin, days=2), gaz)
        assert t.status == "collecting" and t.questions[0].reason == "conflict"

    def test_hue_from_hanoi_is_not_a_conflict(self, gaz):
        assert generate_clarification_turn(req(dest="Huế", origin="Hà Nội", days=2), gaz).status == "ready"

    def test_chua_huong_from_hanoi_is_not_a_conflict(self, gaz):
        t = generate_clarification_turn(req(dest="chùa Hương", origin="Hà Nội", days=1), gaz)
        assert t.status == "ready"

    def test_hoi_an_from_da_nang_is_not_a_conflict(self, gaz):
        assert generate_clarification_turn(req(dest="Hội An", origin="Đà Nẵng", days=2), gaz).status == "ready"

    def test_current_location_never_conflicts(self, gaz):
        assert generate_clarification_turn(req(dest="Hà Nội", origin="CURRENT_LOCATION", days=2), gaz).status == "ready"

    def test_conflict_takes_one_of_the_two_question_slots(self, gaz):
        t = generate_clarification_turn(req(dest="Hà Nội", origin="Hà Nội"), gaz)  # thiếu thêm số ngày
        assert [(q.slot, q.reason) for q in t.questions] == [
            ("destination_mention", "conflict"), ("duration_days", "missing")]

    def test_conflict_cap_respects_config(self, gaz):
        cfg = load_dialogue_config()
        cfg["max_questions_per_turn"] = 1
        t = generate_clarification_turn(req(dest="Hà Nội", origin="Hà Nội"), gaz, cfg)
        assert [q.reason for q in t.questions] == ["conflict"] and t.missing_slots == ["duration_days"]


# ═══════════════════════════════════════════════════════════════════════════════
# apply_chip_event (Mục 7.2: ghi thẳng, không NLU)
# ═══════════════════════════════════════════════════════════════════════════════
class TestApplyChipEvent:
    def test_destination_chip_fills_slot_and_clears_hints(self):
        r = req(regions=["mien_bac"], terrains=["nui"])
        out = apply_chip_event(r, ChipItem(id="chip_dest_sapa", label="Sa Pa", slot="destination_mention", value="Sa Pa"))
        assert out.critical.destination_mention == "Sa Pa"
        assert out.hints.destination_regions == [] and out.hints.terrain_types == []  # quy tắc 4

    def test_input_request_is_not_mutated(self):
        r = req(regions=["mien_bac"])
        before = r.model_dump()
        apply_chip_event(r, {"type": "chip", "slot": "destination_mention", "value": "Sa Pa"})
        assert r.model_dump() == before

    def test_dict_event_form(self):
        out = apply_chip_event(TripRequest(), {"type": "chip", "slot": "duration_days", "value": 3})
        assert out.critical.duration_days == 3

    def test_origin_current_location(self):
        for raw in ("CURRENT_LOCATION", " current_location "):
            out = apply_chip_event(TripRequest(), {"slot": "origin_mention", "value": raw})
            assert out.critical.origin_mention == "CURRENT_LOCATION"

    def test_duration_accepts_numeric_string_from_frontend(self):
        out = apply_chip_event(TripRequest(), {"slot": "duration_days", "value": "4"})
        assert out.critical.duration_days == 4 and isinstance(out.critical.duration_days, int)

    @pytest.mark.parametrize("value", [0, -1, 15, "abc", "2.5", True, None])
    def test_invalid_duration_is_rejected(self, value):
        with pytest.raises(ValueError):
            apply_chip_event(TripRequest(), {"slot": "duration_days", "value": value})

    @pytest.mark.parametrize("slot,value", [
        ("destination_mention", ""), ("destination_mention", "   "), ("origin_mention", None),
        ("group_size", 0), ("group_size", 51),
    ])
    def test_invalid_values_are_rejected(self, slot, value):
        with pytest.raises(ValueError):
            apply_chip_event(TripRequest(), {"slot": slot, "value": value})

    @pytest.mark.parametrize("event", [
        {"type": "chip", "slot": "budget_total_vnd", "value": 5000000},  # dialogue_state sẽ bỏ qua âm thầm
        {"type": "chip", "slot": "status", "value": "ready"},
        {"type": "message", "slot": "duration_days", "value": 3},
        {"slot": "duration_days"},
        "duration_days=3",
    ])
    def test_unsupported_or_malformed_events_are_rejected(self, event):
        with pytest.raises(ValueError):
            apply_chip_event(TripRequest(), event)

    def test_prefer_flight_string_false_is_really_false(self):
        out = apply_chip_event(TripRequest(), {"slot": "prefer_flight", "value": "false"})
        assert out.extra.prefer_flight is False

    def test_chip_clears_defaulted_flag(self):
        r = req(dest="Sa Pa", origin="Hà Nội", days=2)
        r.defaulted = ["duration_days"]
        out = apply_chip_event(r, {"slot": "duration_days", "value": 4})
        assert out.critical.duration_days == 4 and out.defaulted == []

    def test_changing_mind_overwrites_previous_value(self):
        out = apply_chip_event(req(dest="Đà Lạt"), {"slot": "destination_mention", "value": "Sa Pa"})
        assert out.critical.destination_mention == "Sa Pa"

    def test_choosing_a_previously_excluded_place_removes_exclusion(self, gaz):
        r = req(excluded=["Sa Pa"])
        out = apply_chip_event(r, {"slot": "destination_mention", "value": "Sa Pa"}, same_place=gaz.same_entity)
        assert out.critical.destination_mention == "Sa Pa" and out.extra.excluded_mentions == []

    def test_every_chip_we_generate_is_accepted_back(self, gaz):
        for r in (TripRequest(), req(regions=["mien_bac"], terrains=["nui"]), req(dest="Sa Pa"),
                  req(dest="Sa Pa", origin="Hà Nội")):
            for chip in generate_clarification_turn(r, gaz).chips:
                out = apply_chip_event(r, chip)
                assert out is not r
                got = {"destination_mention": out.critical.destination_mention,
                       "origin_mention": out.critical.origin_mention,
                       "duration_days": out.critical.duration_days}[chip.slot]
                assert got == chip.value


# ═══════════════════════════════════════════════════════════════════════════════
# record_turn
# ═══════════════════════════════════════════════════════════════════════════════
class TestRecordTurn:
    def test_records_asked_without_duplicates_and_keeps_collecting(self, gaz):
        r = TripRequest()
        r = record_turn(r, generate_clarification_turn(r, gaz))
        assert r.asked == ["destination_mention", "origin_mention"] and r.status == "collecting"
        r = record_turn(r, generate_clarification_turn(r, gaz))  # hỏi lại cùng câu
        assert r.asked == ["destination_mention", "origin_mention"]

    def test_ready_turn_sets_status_ready(self, gaz):
        r = req(dest="Sa Pa", origin="Hà Nội", days=3)
        assert record_turn(r, generate_clarification_turn(r, gaz)).status == "ready"

    def test_returning_to_collecting_when_user_changes_mind_to_conflict(self, gaz):
        r = req(dest="Hà Nội", origin="Hà Nội", days=2)
        r.status = "ready"
        assert record_turn(r, generate_clarification_turn(r, gaz)).status == "collecting"

    @pytest.mark.parametrize("status", ["planning", "planned", "error"])
    def test_does_not_touch_later_statuses(self, gaz, status):
        r = req(dest="Sa Pa", origin="Hà Nội", days=3)
        r.status = status
        assert record_turn(r, generate_clarification_turn(r, gaz)).status == status

    def test_does_not_mutate_input_or_bump_turn(self, gaz):
        r = TripRequest()
        out = record_turn(r, generate_clarification_turn(r, gaz))
        assert r.asked == [] and out.turn == r.turn == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Kịch bản đầu-cuối (Mục 3): "du lịch miền núi phía bắc" -> bấm chip -> ready
# ═══════════════════════════════════════════════════════════════════════════════
class TestEndToEnd:
    def test_northern_mountains_flow_with_chips_only(self, gaz):
        # Lượt 1: NLU chỉ thấy vùng + địa hình
        r = merge_nlu_slots(TripRequest(), {"destination_regions": ["mien_bac"], "terrain_types": ["nui"]})
        t = generate_clarification_turn(r, gaz)
        r = record_turn(r, t)
        assert [q.slot for q in t.questions] == ["destination_mention", "origin_mention"]
        assert "Sa Pa" in labels(t.questions[0].chips)

        # Bấm "Sa Pa" -> điền điểm đến, hints bị xóa, còn hỏi origin + duration
        sapa = next(c for c in t.chips if c.id == "chip_dest_sapa")
        r = apply_chip_event(r, sapa, same_place=gaz.same_entity)
        t = generate_clarification_turn(r, gaz)
        r = record_turn(r, t)
        assert r.critical.destination_mention == "Sa Pa" and r.hints.destination_regions == []
        assert [q.slot for q in t.questions] == ["origin_mention", "duration_days"]

        # Bấm "Vị trí hiện tại" rồi "3 ngày"
        r = apply_chip_event(r, t.questions[0].chips[0])
        t = generate_clarification_turn(r, gaz)
        assert [q.slot for q in t.questions] == ["duration_days"]
        r = apply_chip_event(r, t.questions[0].chips[2])
        t = generate_clarification_turn(r, gaz)
        r = record_turn(r, t)

        assert t.status == "ready" and r.status == "ready"
        assert (r.critical.destination_mention, r.critical.origin_mention, r.critical.duration_days) == (
            "Sa Pa", "CURRENT_LOCATION", 3)
        assert r.asked == ["destination_mention", "origin_mention", "duration_days"]

    def test_typed_answer_then_chip_mixed(self, gaz):
        r = merge_nlu_slots(TripRequest(), {"destination_mention": "Hội An", "duration_days": 3})
        t = generate_clarification_turn(r, gaz)
        assert [q.slot for q in t.questions] == ["origin_mention"]
        r = apply_chip_event(r, {"type": "chip", "slot": "origin_mention", "value": "Hà Nội"})
        assert generate_clarification_turn(r, gaz).status == "ready"

    def test_picking_origin_equal_to_destination_triggers_conflict_then_recovers(self, gaz):
        r = req(dest="Hà Nội", days=2)
        r = apply_chip_event(r, {"slot": "origin_mention", "value": "Hà Nội"})
        t = generate_clarification_turn(r, gaz)
        assert t.questions[0].reason == "conflict"
        r = apply_chip_event(r, t.questions[0].chips[0])  # chọn điểm đến khác
        assert generate_clarification_turn(r, gaz).status == "ready"


# ═══════════════════════════════════════════════════════════════════════════════
# Gazetteer: danh mục gợi ý + same_entity
# ═══════════════════════════════════════════════════════════════════════════════
class TestGazetteerSuggestions:
    def test_catalog_integrity(self):
        assert len({e.label for e in DESTINATION_CATALOG}) == len(DESTINATION_CATALOG)
        assert len({e.rank for e in DESTINATION_CATALOG}) == len(DESTINATION_CATALOG)  # rank duy nhất = thứ tự ổn định
        for e in DESTINATION_CATALOG:
            assert e.regions and set(e.regions) <= LEAF_REGIONS, e.label
            assert e.terrains and set(e.terrains) <= TERRAIN_TYPES, e.label
            assert e.level in ("province", "locality"), e.label

    def test_every_catalog_label_resolves_to_its_declared_province(self, gaz):
        for e in DESTINATION_CATALOG:
            res = gaz.resolve_mention(e.label, strict=True)
            assert res is not None, f"{e.label} không phân giải được qua gazetteer"
            assert not res["is_ambiguous"], e.label
            assert res["province_code"] == e.province_code, f"{e.label}: {res['province_code']} != {e.province_code}"

    def test_every_catalog_province_exists_in_gazetteer(self, gaz):
        for e in DESTINATION_CATALOG:
            assert e.province_code in gaz.provinces_by_code, e.label

    def test_parent_region_expands_to_child_regions(self):
        got = {e.label for e in rank_destinations(["mien_bac"], [])}
        assert {"Sa Pa", "Hạ Long", "Hà Nội"} <= got and "Đà Nẵng" not in got

    def test_leaf_region_only(self):
        assert [e.label for e in rank_destinations(["tay_bac"], [])] == [
            "Sa Pa", "Mộc Châu", "Mù Cang Chải", "Mai Châu", "Điện Biên", "Tà Xùa"]

    def test_region_and_terrain_must_both_match(self):
        got = rank_destinations(["mien_bac"], ["bien"])
        assert [e.label for e in got][:3] == ["Hạ Long", "Cát Bà", "Cô Tô"]
        assert all("bien" in e.terrains for e in got)

    def test_relaxes_to_region_when_combination_is_empty(self):
        got = rank_destinations(["tay_nam_bo"], ["nui"])  # Tây Nam Bộ không có núi
        assert got and all("tay_nam_bo" in e.regions for e in got)

    def test_unknown_hints_fall_back_to_popular(self):
        assert [e.label for e in rank_destinations(["sao_hoa"], ["mat_trang"])][:2] == ["Đà Nẵng", "Phú Quốc"]

    def test_hint_case_and_whitespace_are_normalised(self):
        assert rank_destinations([" Tay_Bac "], []) == rank_destinations(["tay_bac"], [])

    def test_works_without_a_database(self, tmp_path):
        empty = Gazetteer(str(tmp_path / "missing.db"))
        got = empty.suggest_destinations_by_hints(["tay_bac"], ["nui"], limit=3)
        assert [g["label"] for g in got] == ["Sa Pa", "Mộc Châu", "Mù Cang Chải"]

    @pytest.mark.parametrize("limit", [0, -3, None])
    def test_non_positive_limit_returns_nothing(self, gaz, limit):
        assert gaz.suggest_destinations_by_hints(["tay_bac"], limit=limit) == []

    def test_limit_is_respected(self, gaz):
        assert len(gaz.suggest_destinations_by_hints(limit=4)) == 4

    def test_result_shape(self, gaz):
        first = gaz.suggest_destinations_by_hints(["tay_bac"], ["nui"], limit=1)[0]
        assert first == {"label": "Sa Pa", "province_code": 15, "level": "locality",
                         "regions": ["tay_bac"], "terrains": ["nui"]}


class TestSameEntity:
    @pytest.mark.parametrize("a,b", [
        ("Hà Nội", "ha noi"), ("HN", "Hà Nội"), ("TP.HCM", "Sài Gòn"), ("Sài Gòn", "Hồ Chí Minh"),
        ("Hà Nội", "Hà Nội"),
    ])
    def test_same(self, gaz, a, b):
        assert gaz.same_entity(a, b)

    @pytest.mark.parametrize("a,b", [
        ("chùa Hương", "Hà Nội"),      # Mục 10: điểm cụ thể ≠ tỉnh chứa nó
        ("Hồ Hoàn Kiếm", "Hà Nội"),
        ("Hội An", "Đà Nẵng"),
        ("Vũng Tàu", "TP.HCM"),
        ("Hà Nội", "Đà Nẵng"),
        ("Sa Pa", "Mù Cang Chải"),
        ("CURRENT_LOCATION", "Hà Nội"),
        ("", "Hà Nội"),
        (None, "Hà Nội"),
        ("qn", "Quảng Ninh"),           # viết tắt mơ hồ: không dám khẳng định cùng thực thể
        ("Sao Hỏa", "Hà Nội"),
    ])
    def test_different(self, gaz, a, b):
        assert not gaz.same_entity(a, b)

    def test_usable_as_same_place_hook_for_dialogue_state(self, gaz):
        r = merge_nlu_slots(TripRequest(), {"destination_mention": "Sài Gòn"})
        r = merge_nlu_slots(r, {"excluded_mentions": ["TP.HCM"]}, same_place=gaz.same_entity)
        assert r.critical.destination_mention is None  # bất biến 6: loại trừ mới thắng, tương đương mức thực thể


# ═══════════════════════════════════════════════════════════════════════════════
# MỤC 12B - Tiêu chí nghiệm thu: Hỏi lại và chip (Given / When / Then)
# ═══════════════════════════════════════════════════════════════════════════════
class TestAcceptance12B:
    NLU_NORTH_MOUNTAINS = {"destination_regions": ["mien_bac"], "terrain_types": ["nui"]}  # "du lịch miền núi phía bắc"

    def test_given_typing_northern_mountains_then_hints_set_and_two_questions_with_regional_chips(self, gaz):
        r = merge_nlu_slots(TripRequest(), self.NLU_NORTH_MOUNTAINS)
        # hints.destination_regions có vùng phù hợp, critical còn null
        assert r.hints.destination_regions == ["mien_bac"]
        assert (r.critical.destination_mention, r.critical.origin_mention, r.critical.duration_days) == (None, None, None)

        t = generate_clarification_turn(r, gaz)
        # bot hỏi tối đa 2 câu: điểm đến cụ thể và điểm xuất phát
        assert len(t.questions) <= 2
        assert {q.slot for q in t.questions} == {"destination_mention", "origin_mention"}
        # chip điểm đến đều thuộc vùng núi phía Bắc
        dest_q = next(q for q in t.questions if q.slot == "destination_mention")
        by_label = {e.label: e for e in DESTINATION_CATALOG}
        north = {"tay_bac", "dong_bac", "dong_bang_song_hong"}
        assert dest_q.chips
        for chip in dest_q.chips:
            entry = by_label[chip.value]
            assert set(entry.regions) <= north and "nui" in entry.terrains, chip.label
        assert {"Sa Pa", "Hà Giang"} <= set(labels(dest_q.chips))

    def test_given_clicking_sapa_chip_then_destination_set_without_nlu_and_hints_cleared(self, gaz):
        import app.services.dialogue_state as ds
        r = merge_nlu_slots(TripRequest(), self.NLU_NORTH_MOUNTAINS)
        sapa = next(c for c in generate_clarification_turn(r, gaz).chips if c.label == "Sa Pa")

        real = ds.merge_nlu_slots
        def boom(*a, **k):
            raise AssertionError("NLU/merge không được gọi khi bấm chip")
        ds.merge_nlu_slots = boom  # mọi đường đi qua bước gộp NLU sẽ làm test nổ
        try:
            out = apply_chip_event(r, {"type": "chip", "slot": sapa.slot, "value": sapa.value})
        finally:
            ds.merge_nlu_slots = real

        assert out.critical.destination_mention == "Sa Pa"
        assert out.hints.destination_regions == [] and out.hints.terrain_types == []

    def test_given_then_typing_from_hanoi_then_origin_set_and_destination_kept(self, gaz):
        r = apply_chip_event(merge_nlu_slots(TripRequest(), self.NLU_NORTH_MOUNTAINS),
                             {"slot": "destination_mention", "value": "Sa Pa"})
        # NLU của lượt "từ Hà Nội": destination_mention = None (không nói tới)
        r = merge_nlu_slots(r, {"origin_mention": "Hà Nội", "destination_mention": None})
        assert r.critical.origin_mention == "Hà Nội"
        assert r.critical.destination_mention == "Sa Pa"  # không bị ghi đè bằng null

    def test_given_duration_missing_then_bot_asks_days_with_chips_1_to_5(self, gaz):
        r = req(dest="Sa Pa", origin="Hà Nội")
        t = generate_clarification_turn(r, gaz)
        assert t.missing_slots == ["duration_days"]
        assert [q.slot for q in t.questions] == ["duration_days"]
        assert "mấy ngày" in t.questions[0].text
        assert [c.value for c in t.questions[0].chips] == [1, 2, 3, 4, 5]

    def test_full_12b_chain(self, gaz):
        r = merge_nlu_slots(TripRequest(), self.NLU_NORTH_MOUNTAINS)
        r = apply_chip_event(r, {"type": "chip", "slot": "destination_mention", "value": "Sa Pa"})
        r = merge_nlu_slots(r, {"origin_mention": "Hà Nội"})
        t = generate_clarification_turn(r, gaz)
        assert (r.critical.destination_mention, r.critical.origin_mention) == ("Sa Pa", "Hà Nội")
        assert [q.slot for q in t.questions] == ["duration_days"]
        assert [c.value for c in t.chips] == [1, 2, 3, 4, 5]
