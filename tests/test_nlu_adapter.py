"""tests/test_nlu_adapter.py — adapter extracted -> NLUFlatOutput và luồng NLU -> adapter -> reducer."""
from app.dialogue_models import TripRequest, NLUFlatOutput
from app.services.nlu_adapter import extracted_to_nlu_flat
from app.services.dialogue_state import merge_nlu_slots

FULL = {
    "intent": "plan_itinerary", "origin": "Hà Nội", "destination": "Đà Nẵng", "days": 3, "duration_days": 3,
    "group_size": 4, "vehicle_type": "Car", "budget_total_vnd": 5000000, "prefer_flight": False,
    "destination_regions": [], "terrain_types": [], "excluded_destinations": ["Huế"], "excluded_places": ["Bà Nà Hills"],
    "hard_pinned_locations": ["Hội An"], "must_visit_places": ["Hội An"], "preferences": ["biển"], "excluded_activities": ["karaoke"],
}


def test_full_mapping():
    n = extracted_to_nlu_flat(FULL, raw_query="q")
    assert (n.intent, n.destination_mention, n.origin_mention, n.duration_days, n.group_size) == ("plan_itinerary", "Đà Nẵng", "Hà Nội", 3, 4)
    assert n.vehicle_type == "car" and n.budget_total_vnd == 5000000.0 and n.prefer_flight is False
    assert n.excluded_mentions == ["Huế", "Bà Nà Hills"] and n.pinned_mentions == ["Hội An"]
    assert n.preferences == ["biển"] and n.excluded_activities == ["karaoke"] and n.raw_query == "q"


def test_hints_pass_through_when_no_destination():
    n = extracted_to_nlu_flat({"intent": "plan_itinerary", "destination_regions": ["NORTH"], "terrain_types": ["MOUNTAIN"]})
    assert n.destination_mention is None and n.destination_regions == ["NORTH"] and n.terrain_types == ["MOUNTAIN"]


def test_intent_always_explicit_never_defaulted():
    for bad in (None, "", "banana", 5):
        n = extracted_to_nlu_flat({"intent": bad})
        assert n.intent is None and "intent" in n.model_fields_set
    assert extracted_to_nlu_flat({}).intent is None and extracted_to_nlu_flat(None).intent is None
    assert extracted_to_nlu_flat({"intent": "PLAN_TRIP"}).intent == "plan_itinerary"
    assert extracted_to_nlu_flat({"intent": "ask_advisory"}).intent == "ask_advisory"


def test_unknown_intent_does_not_reset_state():
    req = merge_nlu_slots(TripRequest(), NLUFlatOutput(intent="ask_advisory"))
    req = merge_nlu_slots(req, extracted_to_nlu_flat({"destination": "Huế"}))
    assert req.intent == "ask_advisory" and req.critical.destination_mention == "Huế"


def test_missing_slots_stay_none_not_defaulted():
    n = extracted_to_nlu_flat({"intent": "plan_itinerary", "destination": "Đà Nẵng", "days": 3})
    assert n.origin_mention is None and n.group_size is None and n.vehicle_type is None
    assert n.prefer_flight is None and n.budget_total_vnd is None


def test_current_location_normalised():
    for spelled in ("CURRENT_LOCATION", "current_location", " Current Location "):
        assert extracted_to_nlu_flat({"origin": spelled}).origin_mention == "CURRENT_LOCATION"


def test_out_of_range_numbers_become_none_not_clamped():
    n = extracted_to_nlu_flat({"days": 30, "group_size": 0, "budget_total_vnd": -5})
    assert n.duration_days is None and n.group_size is None and n.budget_total_vnd is None
    n = extracted_to_nlu_flat({"days": 14, "group_size": 50})
    assert n.duration_days == 14 and n.group_size == 50
    n = extracted_to_nlu_flat({"days": "3", "group_size": "2.0"})
    assert n.duration_days == 3 and n.group_size == 2
    n = extracted_to_nlu_flat({"days": 3.5, "group_size": True, "budget_total_vnd": "5 triệu"})
    assert n.duration_days is None and n.group_size is None and n.budget_total_vnd is None


def test_days_falls_back_to_duration_days_key():
    assert extracted_to_nlu_flat({"duration_days": 2}).duration_days == 2


def test_garbage_types_never_raise():
    n = extracted_to_nlu_flat({"intent": 1, "destination": ["x"], "origin": 3, "preferences": "biển", "excluded_places": {"a": 1},
                               "hard_pinned_locations": "Hội An", "prefer_flight": "maybe", "vehicle_type": 7})
    assert n.destination_mention is None and n.origin_mention is None and n.vehicle_type is None
    assert n.preferences == ["biển"] and n.pinned_mentions == ["Hội An"] and n.excluded_mentions == [] and n.prefer_flight is None


def test_excluded_merge_dedupes_in_order():
    n = extracted_to_nlu_flat({"excluded_destinations": ["Huế", "Hải Phòng"], "excluded_places": ["Hải Phòng", "Đồ Sơn"]})
    assert n.excluded_mentions == ["Huế", "Hải Phòng", "Đồ Sơn"]


def test_flight_vehicle_goes_to_prefer_flight():
    n = extracted_to_nlu_flat({"vehicle_type": "plane"})
    assert n.vehicle_type is None and n.prefer_flight is True
    n = extracted_to_nlu_flat({"vehicle_type": "flight", "prefer_flight": False})
    assert n.vehicle_type is None and n.prefer_flight is False


def test_string_prefer_flight_values():
    assert extracted_to_nlu_flat({"prefer_flight": "true"}).prefer_flight is True
    assert extracted_to_nlu_flat({"prefer_flight": "false"}).prefer_flight is False


def test_end_to_end_normalizer_adapter_reducer():
    """LLM JSON thô -> _normalize_extracted_slots -> adapter -> merge: đổi ý Đà Nẵng -> Huế rồi loại trừ Huế."""
    from app.services.prompt_nlu_service import _normalize_extracted_slots as norm
    req = merge_nlu_slots(TripRequest(), extracted_to_nlu_flat(norm(
        {"intent": "plan_itinerary", "origin": "Hà Nội", "destination": "Đà Nẵng", "duration_days": 3, "group_size": 2})))
    assert (req.critical.destination_mention, req.critical.origin_mention, req.critical.duration_days) == ("Đà Nẵng", "Hà Nội", 3)
    req = merge_nlu_slots(req, extracted_to_nlu_flat(norm(
        {"intent": "plan_itinerary", "destination": "Huế", "excluded_destinations": ["Đà Nẵng"]})))
    assert req.critical.destination_mention == "Huế" and req.extra.excluded_mentions == ["Đà Nẵng"]
    assert req.critical.origin_mention == "Hà Nội" and req.critical.duration_days == 3      # không bị ghi đè bởi null
    req = merge_nlu_slots(req, extracted_to_nlu_flat(norm({"intent": "ask_advisory", "excluded_destinations": ["Huế"]})))
    assert req.critical.destination_mention is None and req.intent == "ask_advisory"
    req = merge_nlu_slots(req, extracted_to_nlu_flat(norm({"intent": "plan_itinerary", "destination": "Sa Pa"})))
    assert req.critical.destination_mention == "Sa Pa" and req.intent == "plan_itinerary"


def test_raw_extracted_passed_directly_loses_slots_documenting_the_need_for_adapter():
    """Bằng chứng vì sao cần adapter: NLUFlatOutput(**extracted) bỏ qua khóa lạ (origin, destination, hard_pinned_locations...)."""
    direct = NLUFlatOutput(**FULL)
    assert direct.destination_mention is None and direct.origin_mention is None
    assert direct.pinned_mentions == [] and direct.excluded_mentions == []
