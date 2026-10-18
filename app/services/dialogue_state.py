"""
app/services/dialogue_state.py
===============================================================================
Lớp xử lý trạng thái hội thoại (Dialogue State Reducer) thuần túy (Pure Function)
Tuân thủ nghiêm ngặt 5 quy tắc gộp của Mục 5 & Mục 10 trong docs/PRODUCT_SPEC.md:

1. Slot mới có giá trị thì ghi vào. Slot mới là null hoặc [] thì KHÔNG ghi đè giá trị cũ.
2. Người dùng đổi ý ("thôi đi Sa Pa") thì giá trị mới ghi đè giá trị cũ.
3. Danh sách (excluded_mentions, pinned_mentions, preferences, excluded_activities)
   gộp và loại trùng, trừ khi người dùng nói rõ muốn thay thế.
4. Nếu destination_mention đã có thì XÓA hints.destination_regions và hints.terrain_types.
5. Quản lý danh sách defaulted: nếu người dùng nói ra một slot đang nằm trong defaulted,
   slot đó phải được loại khỏi defaulted.

Bất biến loại trừ (bổ sung, hợp với quy tắc 2 "đổi ý thì giá trị mới thắng"):
6. Điểm đến / điểm bắt buộc KHÔNG được đồng thời nằm trong excluded_mentions. Lượt nói sau thắng:
   - Loại trừ mới trùng destination_mention hiện có -> destination_mention bị xóa (hỏi lại điểm đến);
     trùng pinned_mentions hiện có -> bị gỡ khỏi pinned_mentions.
   - Điểm đến / điểm bắt buộc mới trùng một loại trừ CŨ -> loại trừ cũ bị gỡ (người dùng đã đổi ý).
   - Mâu thuẫn ngay trong MỘT lượt (vừa muốn vừa loại trừ cùng địa danh) -> loại trừ thắng, giá trị muốn bị bỏ qua.
   So khớp không phân biệt hoa/thường và dấu. Tương đương mức thực thể (TP.HCM = Sài Gòn) thuộc về gazetteer:
   truyền `same_place(a, b) -> bool` nếu muốn dùng; mặc định chỉ so khớp văn bản, hàm vẫn thuần túy.

intent là intent của lượt gần nhất có intent hợp lệ (không còn "dính"): plan_itinerary ghi đè lại
ask_advisory/search_place/clarify_needed của lượt trước. Intent thiếu / None / không hợp lệ thì giữ nguyên.
"""
import logging
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Union
from app.dialogue_models import TripRequest, NLUFlatOutput, CriticalSlots, ExtraSlots, HintsSlots

logger = logging.getLogger("dialogue_state")

VALID_INTENTS = {"plan_itinerary", "search_place", "ask_advisory", "clarify_needed"}
_INTENT_ALIASES = {"plan_trip": "plan_itinerary"}
SamePlace = Callable[[str, str], bool]


def _canon_intent(value: Any) -> Optional[str]:
    s = str(value or "").strip().lower()
    s = _INTENT_ALIASES.get(s, s)
    return s if s in VALID_INTENTS else None


def _place_key(text: str) -> str:
    """Khóa so khớp địa danh: không dấu, không hoa/thường, bỏ dấu câu, gộp khoảng trắng."""
    s = unicodedata.normalize("NFD", str(text).replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _same(a: str, b: str, same_place: Optional[SamePlace]) -> bool:
    if _place_key(a) == _place_key(b):
        return True
    if same_place is not None:
        try:
            return bool(same_place(a, b))
        except Exception as e:  # hook lỗi không được làm sập reducer
            logger.warning("same_place(%r, %r) lỗi: %s", a, b, e)
    return False


def _any_same(name: str, items: List[str], same_place: Optional[SamePlace]) -> bool:
    return any(_same(name, x, same_place) for x in items)


def _drop_same(items: List[str], names: List[str], same_place: Optional[SamePlace]) -> List[str]:
    return [x for x in items if not _any_same(x, names, same_place)]


def _clean_list(items: Optional[List[Any]]) -> List[str]:
    return [str(x).strip() for x in (items or []) if str(x).strip()]


def _merge_list_unique(existing_list: List[str], new_items: Optional[List[str]]) -> List[str]:
    """Gộp danh sách và loại bỏ trùng lặp, bảo toàn thứ tự xuất hiện."""
    if not new_items:
        return list(existing_list)
    seen = set(existing_list)
    result = list(existing_list)
    for item in new_items:
        clean_item = str(item).strip()
        if clean_item and clean_item not in seen:
            seen.add(clean_item)
            result.append(clean_item)
    return result


def _apply_new_exclusions(
    updated: TripRequest,
    new_excluded: List[str],
    defaulted_set: set,
    same_place: Optional[SamePlace],
) -> None:
    """Loại trừ mới thắng điểm đến / điểm bắt buộc đã lưu (bất biến 6). Sửa trực tiếp `updated` (đã là bản copy)."""
    dest = updated.critical.destination_mention
    if dest and _any_same(dest, new_excluded, same_place):
        updated.critical.destination_mention = None
        defaulted_set.discard("destination_mention")
    updated.extra.pinned_mentions = _drop_same(updated.extra.pinned_mentions, new_excluded, same_place)


def merge_nlu_slots(
    current_request: TripRequest,
    nlu_output: Union[NLUFlatOutput, Dict[str, Any]],
    same_place: Optional[SamePlace] = None,
) -> TripRequest:
    """
    Gộp kết quả NLU phẳng vào TripRequest theo 5 quy tắc chuẩn.
    Trả về một bản copy mới (immutability pattern) để tránh race-conditions.
    """
    if isinstance(nlu_output, dict):
        nlu_data = NLUFlatOutput(**nlu_output)
    else:
        nlu_data = nlu_output

    # Clone dữ liệu hiện tại
    updated = current_request.model_copy(deep=True)
    defaulted_set = set(updated.defaulted)

    # Loại trừ của LƯỢT NÀY (thắng mọi thứ cùng lượt, xem bất biến 6)
    new_excluded = _clean_list(nlu_data.excluded_mentions)

    # 1. Cập nhật Critical Slots
    # destination_mention
    if nlu_data.destination_mention is not None and str(nlu_data.destination_mention).strip():
        val = str(nlu_data.destination_mention).strip()
        if _any_same(val, new_excluded, same_place):
            logger.warning("NLU mâu thuẫn trong một lượt: %r vừa là điểm đến vừa bị loại trừ -> bỏ qua điểm đến", val)
        else:
            updated.critical.destination_mention = val
            defaulted_set.discard("destination_mention")
            # Người dùng giờ muốn chính địa danh này: loại trừ cũ (nếu có) hết hiệu lực
            updated.extra.excluded_mentions = _drop_same(updated.extra.excluded_mentions, [val], same_place)
            # Quy tắc 4: Khi đã có điểm đến cụ thể thì xóa hints
            updated.hints.destination_regions = []
            updated.hints.terrain_types = []

    # origin_mention
    if nlu_data.origin_mention is not None and str(nlu_data.origin_mention).strip():
        updated.critical.origin_mention = str(nlu_data.origin_mention).strip()
        defaulted_set.discard("origin_mention")

    # duration_days
    if nlu_data.duration_days is not None and nlu_data.duration_days >= 1:
        updated.critical.duration_days = nlu_data.duration_days
        defaulted_set.discard("duration_days")

    # 2. Cập nhật Extra Slots
    # group_size
    if nlu_data.group_size is not None and nlu_data.group_size >= 1:
        updated.extra.group_size = nlu_data.group_size
        defaulted_set.discard("group_size")

    # budget_total_vnd
    if nlu_data.budget_total_vnd is not None and nlu_data.budget_total_vnd > 0:
        updated.extra.budget_total_vnd = float(nlu_data.budget_total_vnd)
        defaulted_set.discard("budget_total_vnd")

    # vehicle_type
    if nlu_data.vehicle_type is not None and str(nlu_data.vehicle_type).strip():
        updated.extra.vehicle_type = str(nlu_data.vehicle_type).strip().lower()
        defaulted_set.discard("vehicle_type")

    # prefer_flight
    if nlu_data.prefer_flight is not None:
        updated.extra.prefer_flight = bool(nlu_data.prefer_flight)
        defaulted_set.discard("prefer_flight")

    # Danh sách gộp và loại trùng
    if nlu_data.preferences:
        updated.extra.preferences = _merge_list_unique(updated.extra.preferences, nlu_data.preferences)
        defaulted_set.discard("preferences")

    if nlu_data.pinned_mentions:
        new_pinned = [p for p in _clean_list(nlu_data.pinned_mentions) if not _any_same(p, new_excluded, same_place)]
        if len(new_pinned) != len(_clean_list(nlu_data.pinned_mentions)):
            logger.warning("NLU mâu thuẫn trong một lượt: bỏ qua điểm bắt buộc trùng danh sách loại trừ")
        updated.extra.excluded_mentions = _drop_same(updated.extra.excluded_mentions, new_pinned, same_place)
        updated.extra.pinned_mentions = _merge_list_unique(updated.extra.pinned_mentions, new_pinned)
        defaulted_set.discard("pinned_mentions")

    if nlu_data.excluded_mentions:
        updated.extra.excluded_mentions = _merge_list_unique(updated.extra.excluded_mentions, new_excluded)
        defaulted_set.discard("excluded_mentions")
        _apply_new_exclusions(updated, new_excluded, defaulted_set, same_place)

    if nlu_data.excluded_activities:
        updated.extra.excluded_activities = _merge_list_unique(updated.extra.excluded_activities, nlu_data.excluded_activities)
        defaulted_set.discard("excluded_activities")

    # 3. Cập nhật Hints Slots (chỉ khi chưa có destination_mention)
    if not updated.critical.destination_mention:
        if nlu_data.destination_regions:
            updated.hints.destination_regions = _merge_list_unique(updated.hints.destination_regions, nlu_data.destination_regions)
        if nlu_data.terrain_types:
            updated.hints.terrain_types = _merge_list_unique(updated.hints.terrain_types, nlu_data.terrain_types)

    # Intent của lượt gần nhất. NLUFlatOutput.intent mặc định "plan_itinerary" nên chỉ tin intent khi nó
    # THỰC SỰ được cung cấp (model_fields_set); thiếu / None / không hợp lệ -> giữ intent hiện có.
    fields_set = getattr(nlu_data, "model_fields_set", None)
    if fields_set is None or "intent" in fields_set:
        intent = _canon_intent(nlu_data.intent)
        if intent:
            updated.intent = intent

    updated.defaulted = sorted(list(defaulted_set))
    return updated


def apply_chip_selection(
    current_request: TripRequest,
    slot_name: str,
    value: Any,
    same_place: Optional[SamePlace] = None,
) -> TripRequest:
    """
    Áp dụng trực tiếp lựa chọn từ nút gợi ý (chip) vào slot tương ứng.
    Bypass hoàn toàn NLU model.
    """
    updated = current_request.model_copy(deep=True)
    defaulted_set = set(updated.defaulted)

    if slot_name == "destination_mention":
        updated.critical.destination_mention = str(value).strip()
        defaulted_set.discard("destination_mention")
        # Bấm chọn một địa danh từng bị loại trừ = đổi ý: gỡ loại trừ cũ
        updated.extra.excluded_mentions = _drop_same(updated.extra.excluded_mentions, [updated.critical.destination_mention], same_place)
        # Xóa hints khi đã chọn điểm đến cụ thể
        updated.hints.destination_regions = []
        updated.hints.terrain_types = []
    elif slot_name == "origin_mention":
        updated.critical.origin_mention = str(value).strip()
        defaulted_set.discard("origin_mention")
    elif slot_name == "duration_days":
        updated.critical.duration_days = int(value)
        defaulted_set.discard("duration_days")
    elif slot_name == "group_size":
        updated.extra.group_size = int(value)
        defaulted_set.discard("group_size")
    elif slot_name == "vehicle_type":
        updated.extra.vehicle_type = str(value).strip().lower()
        defaulted_set.discard("vehicle_type")
    elif slot_name == "prefer_flight":
        updated.extra.prefer_flight = bool(value)
        defaulted_set.discard("prefer_flight")
    elif slot_name == "pinned_mentions":
        val = str(value).strip()
        updated.extra.excluded_mentions = _drop_same(updated.extra.excluded_mentions, [val], same_place)
        updated.extra.pinned_mentions = _merge_list_unique(updated.extra.pinned_mentions, [val])
    elif slot_name == "excluded_mentions":
        val = str(value).strip()
        updated.extra.excluded_mentions = _merge_list_unique(updated.extra.excluded_mentions, [val])
        _apply_new_exclusions(updated, [val] if val else [], defaulted_set, same_place)

    updated.defaulted = sorted(list(defaulted_set))
    return updated


def apply_default_slot(
    current_request: TripRequest,
    slot_name: str,
    default_value: Any
) -> TripRequest:
    """
    Gán giá trị mặc định cho một slot khi người dùng từ chối trả lời hoặc quá số lượt hỏi.
    Slot này sẽ được ghi nhận vào danh sách `defaulted` để phân biệt với slot do người dùng nói.
    """
    updated = current_request.model_copy(deep=True)
    defaulted_set = set(updated.defaulted)

    if slot_name == "group_size" and updated.extra.group_size is None:
        updated.extra.group_size = int(default_value)
        defaulted_set.add("group_size")
    elif slot_name == "duration_days" and updated.critical.duration_days is None:
        updated.critical.duration_days = int(default_value)
        defaulted_set.add("duration_days")
    elif slot_name == "origin_mention" and updated.critical.origin_mention is None:
        updated.critical.origin_mention = str(default_value)
        defaulted_set.add("origin_mention")
    elif slot_name == "destination_mention" and updated.critical.destination_mention is None:
        updated.critical.destination_mention = str(default_value)
        defaulted_set.add("destination_mention")
    elif slot_name == "budget_total_vnd" and updated.extra.budget_total_vnd is None:
        updated.extra.budget_total_vnd = float(default_value) if default_value is not None else None
        if default_value is not None:
            defaulted_set.add("budget_total_vnd")

    updated.defaulted = sorted(list(defaulted_set))
    return updated
