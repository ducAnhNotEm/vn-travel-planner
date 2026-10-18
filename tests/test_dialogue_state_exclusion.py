"""
tests/test_dialogue_state_exclusion.py
Bổ sung cho tests/test_dialogue_state.py (không sửa file đó): intent không còn "dính" và bất biến loại trừ.
"""
from app.dialogue_models import TripRequest, NLUFlatOutput
from app.services.dialogue_state import merge_nlu_slots, apply_chip_selection, apply_default_slot


def _with_dest(dest="Đà Nẵng"):
    return merge_nlu_slots(TripRequest(), NLUFlatOutput(destination_mention=dest))


# ── intent không dính ───────────────────────────────────────────────────────────
def test_intent_not_sticky_after_advisory():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(intent="ask_advisory"))
    assert req.intent == "ask_advisory"
    req = merge_nlu_slots(req, NLUFlatOutput(intent="plan_itinerary", duration_days=3))
    assert req.intent == "plan_itinerary"          # trước đây kẹt ở ask_advisory


def test_intent_switches_between_all_valid_values():
    req = TripRequest()
    for i in ("search_place", "clarify_needed", "ask_advisory", "plan_itinerary"):
        req = merge_nlu_slots(req, NLUFlatOutput(intent=i))
        assert req.intent == i


def test_intent_none_unknown_or_absent_keeps_current():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(intent="ask_advisory"))
    assert merge_nlu_slots(req, NLUFlatOutput(intent=None)).intent == "ask_advisory"
    assert merge_nlu_slots(req, NLUFlatOutput(intent="banana")).intent == "ask_advisory"
    # thiếu hẳn khóa intent: default "plan_itinerary" của NLUFlatOutput KHÔNG được coi là NLU đã xác nhận
    assert merge_nlu_slots(req, NLUFlatOutput(duration_days=2)).intent == "ask_advisory"
    assert merge_nlu_slots(req, {"duration_days": 2}).intent == "ask_advisory"


def test_intent_alias_plan_trip():
    req = merge_nlu_slots(merge_nlu_slots(TripRequest(), NLUFlatOutput(intent="ask_advisory")), {"intent": "PLAN_TRIP"})
    assert req.intent == "plan_itinerary"


# ── loại trừ xóa điểm đến cũ ──────────────────────────────────────────────────────
def test_exclusion_clears_current_destination():
    req = _with_dest("Đà Nẵng")
    req = merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Đà Nẵng"]))
    assert req.critical.destination_mention is None
    assert req.extra.excluded_mentions == ["Đà Nẵng"]


def test_exclusion_match_ignores_case_and_accents():
    for spelled in ("đà nẵng", "DA NANG", "  Da  Nang "):
        req = merge_nlu_slots(_with_dest("Đà Nẵng"), NLUFlatOutput(excluded_mentions=[spelled]))
        assert req.critical.destination_mention is None, spelled


def test_exclusion_removes_defaulted_flag_of_cleared_destination():
    req = apply_default_slot(TripRequest(), "destination_mention", "Hà Nội")
    assert "destination_mention" in req.defaulted
    req = merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Hà Nội"]))
    assert req.critical.destination_mention is None and "destination_mention" not in req.defaulted


def test_unrelated_exclusion_keeps_destination():
    req = merge_nlu_slots(_with_dest("Đà Nẵng"), NLUFlatOutput(excluded_mentions=["Bà Nà Hills"]))
    assert req.critical.destination_mention == "Đà Nẵng"


def test_change_of_mind_new_destination_and_old_excluded():
    """'Không phải Đà Nẵng, tao muốn Huế'"""
    req = merge_nlu_slots(_with_dest("Đà Nẵng"), NLUFlatOutput(destination_mention="Huế", excluded_mentions=["Đà Nẵng"]))
    assert req.critical.destination_mention == "Huế"
    assert req.extra.excluded_mentions == ["Đà Nẵng"]


def test_exclusion_then_hints_in_same_turn_are_kept():
    """'Không đi Đà Nẵng nữa, tao muốn đi biển miền Trung': điểm đến bị xóa nên hints mới phải được nhận."""
    req = merge_nlu_slots(_with_dest("Đà Nẵng"), NLUFlatOutput(excluded_mentions=["Đà Nẵng"],
                                                                 destination_regions=["CENTRAL"], terrain_types=["BEACH"]))
    assert req.critical.destination_mention is None
    assert req.hints.destination_regions == ["CENTRAL"] and req.hints.terrain_types == ["BEACH"]


def test_same_turn_contradiction_exclusion_wins():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(destination_mention="Huế", excluded_mentions=["Huế"]))
    assert req.critical.destination_mention is None
    assert req.extra.excluded_mentions == ["Huế"]
    # điểm đến cũ vẫn bị xóa khi cùng địa danh bị loại trừ; điểm đến cũ khác thì giữ
    req2 = merge_nlu_slots(_with_dest("Đà Lạt"), NLUFlatOutput(destination_mention="Huế", excluded_mentions=["Huế"]))
    assert req2.critical.destination_mention == "Đà Lạt"


# ── loại trừ cũ hết hiệu lực khi người dùng đổi ý ─────────────────────────────────
def test_new_destination_removes_stale_exclusion():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(excluded_mentions=["Hải Phòng", "Đồ Sơn"]))
    req = merge_nlu_slots(req, NLUFlatOutput(destination_mention="hải phòng"))
    assert req.critical.destination_mention == "hải phòng"
    assert req.extra.excluded_mentions == ["Đồ Sơn"]


def test_pinned_vs_excluded_both_directions():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(pinned_mentions=["Bà Nà Hills", "Cầu Rồng"]))
    req = merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["bà nà hills"]))          # loại trừ mới gỡ pinned cũ
    assert req.extra.pinned_mentions == ["Cầu Rồng"]
    assert req.extra.excluded_mentions == ["bà nà hills"]
    req = merge_nlu_slots(req, NLUFlatOutput(pinned_mentions=["Bà Nà Hills"]))            # đổi ý: pinned mới gỡ loại trừ cũ
    assert req.extra.pinned_mentions == ["Cầu Rồng", "Bà Nà Hills"]
    assert req.extra.excluded_mentions == []
    req = merge_nlu_slots(req, NLUFlatOutput(pinned_mentions=["Hội An"], excluded_mentions=["Hội An"]))  # cùng lượt
    assert "Hội An" not in req.extra.pinned_mentions and "Hội An" in req.extra.excluded_mentions


# ── chip ────────────────────────────────────────────────────────────────────────
def test_chip_excluded_clears_destination_and_pinned():
    req = merge_nlu_slots(_with_dest("Sa Pa"), NLUFlatOutput(pinned_mentions=["Fansipan"]))
    req = apply_chip_selection(req, "excluded_mentions", "Sa Pa")
    assert req.critical.destination_mention is None
    req = apply_chip_selection(req, "excluded_mentions", "Fansipan")
    assert req.extra.pinned_mentions == []


def test_chip_destination_and_pinned_remove_stale_exclusion():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(excluded_mentions=["Sa Pa", "Fansipan"]))
    req = apply_chip_selection(req, "destination_mention", "Sa Pa")
    req = apply_chip_selection(req, "pinned_mentions", "Fansipan")
    assert req.extra.excluded_mentions == [] and req.extra.pinned_mentions == ["Fansipan"]


# ── same_place hook & tính thuần túy ──────────────────────────────────────────────
def test_same_place_hook_for_aliases():
    alias = lambda a, b: {a.lower(), b.lower()} == {"tp.hcm", "sài gòn"}
    req = _with_dest("TP.HCM")
    assert merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Sài Gòn"])).critical.destination_mention == "TP.HCM"  # mặc định: chỉ so văn bản
    assert merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Sài Gòn"]), same_place=alias).critical.destination_mention is None
    boom = lambda a, b: 1 / 0
    assert merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Sài Gòn"]), same_place=boom).critical.destination_mention == "TP.HCM"


def test_merge_does_not_mutate_input():
    req = _with_dest("Đà Nẵng")
    before = req.model_dump()
    merge_nlu_slots(req, NLUFlatOutput(excluded_mentions=["Đà Nẵng"], intent="ask_advisory"))
    assert req.model_dump() == before
