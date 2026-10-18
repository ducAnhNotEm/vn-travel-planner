"""
app/services/nlu_adapter.py
===============================================================================
Adapter: đầu ra chuẩn hóa của NLU (`parse_prompt_unified(...)["extracted"]`) -> `NLUFlatOutput`
(app/dialogue_models.py), đầu vào của `dialogue_state.merge_nlu_slots`.

Hai bên đặt tên khác nhau nên truyền thẳng `extracted` vào NLUFlatOutput sẽ làm mất gần hết slot
(pydantic bỏ qua khóa lạ):

    extracted                                    NLUFlatOutput
    ------------------------------------------   --------------------------------
    destination                              ->  destination_mention
    origin                                   ->  origin_mention  ("CURRENT_LOCATION" giữ nguyên)
    duration_days | days                     ->  duration_days   (1..14, ngoài khoảng -> None)
    group_size                               ->  group_size      (1..50, ngoài khoảng -> None)
    budget_total_vnd                         ->  budget_total_vnd (> 0)
    hard_pinned_locations | must_visit_places->  pinned_mentions
    excluded_destinations + excluded_places  ->  excluded_mentions (gộp, loại trùng)
    vehicle_type, prefer_flight, preferences, excluded_activities, destination_regions, terrain_types
                                             ->  cùng tên

Nguyên tắc:
- Thuần túy, không I/O, không gọi gazetteer, không import prompt_nlu_service.
- Không bịa: giá trị sai kiểu / ngoài khoảng của model -> None ("chưa nói"), có log; không kẹp (clamp) số.
- `intent` LUÔN được truyền tường minh (None nếu không hợp lệ). NLUFlatOutput.intent mặc định "plan_itinerary",
  nên bỏ trống sẽ làm reducer tưởng NLU đã xác nhận plan_itinerary.
- destination_regions / terrain_types giữ nguyên từ vựng của NLU (NORTH, MOUNTAIN, ...). Từ vựng này khác với
  ví dụ trong dialogue_models.py (mien_bac, nui); khi viết nguồn gợi ý `gazetteer_by_hints` phải chốt một bên.

Cách dùng:
    res = parse_prompt_unified(prompt)
    if res["success"]:
        nlu = extracted_to_nlu_flat(res["extracted"], raw_query=prompt)
        request = merge_nlu_slots(request, nlu)
"""
import logging
import math
from typing import Any, Dict, List, Optional

from app.dialogue_models import NLUFlatOutput

logger = logging.getLogger("nlu_adapter")

CURRENT_LOCATION = "CURRENT_LOCATION"
DURATION_RANGE = (1, 14)   # khớp CriticalSlots.duration_days
GROUP_RANGE = (1, 50)      # khớp ExtraSlots.group_size

# Đồng bộ với INTENT_ALIASES của prompt_nlu_service.
_VALID_INTENTS = {"plan_itinerary", "search_place", "ask_advisory", "clarify_needed"}
_INTENT_ALIASES = {"plan_trip": "plan_itinerary"}
# Máy bay được biểu diễn bằng prefer_flight, không phải vehicle_type (tập vehicle_type của planner: car/motorbike/taxi/van).
_FLIGHT_VEHICLES = {"plane", "flight", "airplane"}


def _intent(v: Any) -> Optional[str]:
    s = str(v or "").strip().lower()
    s = _INTENT_ALIASES.get(s, s)
    return s if s in _VALID_INTENTS else None


def _str(v: Any) -> Optional[str]:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def _str_list(v: Any) -> List[str]:
    """Chuỗi đơn -> [chuỗi]; kiểu lạ -> []. Không bao giờ tách chuỗi thành từng ký tự. Giữ thứ tự, bỏ trùng."""
    if isinstance(v, str):
        v = [v]
    elif not isinstance(v, (list, tuple, set)):
        return []
    out: List[str] = []
    for x in v:
        s = _str(x)
        if s and s not in out:
            out.append(s)
    return out


def _number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    elif isinstance(v, str):
        try:
            x = float(v.replace(",", "").strip())
        except ValueError:
            return None
    else:
        return None
    return x if math.isfinite(x) else None


def _int_in_range(slot: str, v: Any, lo: int, hi: int) -> Optional[int]:
    if v is None:
        return None
    x = _number(v)
    if x is None or x != int(x) or not (lo <= int(x) <= hi):
        logger.warning("Adapter: %s=%r ngoài khoảng [%d, %d] hoặc không phải số nguyên -> None", slot, v, lo, hi)
        return None
    return int(x)


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "có"):
            return True
        if s in ("false", "0", "no", "không"):
            return False
    return None


def extracted_to_nlu_flat(extracted: Optional[Dict[str, Any]], raw_query: Optional[str] = None) -> NLUFlatOutput:
    """Chuyển `extracted` của NLU service sang NLUFlatOutput. Không bao giờ ném lỗi vì dữ liệu NLU xấu."""
    d = extracted if isinstance(extracted, dict) else {}

    origin = _str(d.get("origin"))
    if origin and origin.upper().replace(" ", "_") == CURRENT_LOCATION:
        origin = CURRENT_LOCATION

    duration = None
    for key in ("duration_days", "days"):
        if d.get(key) is not None:
            duration = _int_in_range("duration_days", d.get(key), *DURATION_RANGE)
            break

    budget = _number(d.get("budget_total_vnd"))
    budget = budget if budget is not None and budget > 0 else None

    prefer_flight = _bool(d.get("prefer_flight"))
    vehicle = _str(d.get("vehicle_type"))
    vehicle = vehicle.lower() if vehicle else None
    if vehicle in _FLIGHT_VEHICLES:
        if prefer_flight is False:
            logger.warning("Adapter: vehicle_type=%r mâu thuẫn prefer_flight=False -> giữ prefer_flight, bỏ vehicle_type", vehicle)
        elif prefer_flight is None:
            prefer_flight = True
        vehicle = None

    excluded = _str_list(_str_list(d.get("excluded_destinations")) + _str_list(d.get("excluded_places")))
    pinned = _str_list(d.get("hard_pinned_locations") or d.get("must_visit_places"))

    return NLUFlatOutput(
        intent=_intent(d.get("intent")),          # tường minh, kể cả None
        destination_mention=_str(d.get("destination")),
        destination_regions=_str_list(d.get("destination_regions")),
        terrain_types=_str_list(d.get("terrain_types")),
        excluded_mentions=excluded,
        origin_mention=origin,
        duration_days=duration,
        group_size=_int_in_range("group_size", d.get("group_size"), *GROUP_RANGE),
        vehicle_type=vehicle,
        budget_total_vnd=budget,
        preferences=_str_list(d.get("preferences")),
        excluded_activities=_str_list(d.get("excluded_activities")),
        pinned_mentions=pinned,
        prefer_flight=prefer_flight,
        raw_query=raw_query,
    )
