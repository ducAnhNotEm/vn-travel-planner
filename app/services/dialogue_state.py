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
"""
from typing import Any, Dict, List, Optional, Union
from app.dialogue_models import TripRequest, NLUFlatOutput, CriticalSlots, ExtraSlots, HintsSlots


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


def merge_nlu_slots(
    current_request: TripRequest,
    nlu_output: Union[NLUFlatOutput, Dict[str, Any]]
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

    # 1. Cập nhật Critical Slots
    # destination_mention
    if nlu_data.destination_mention is not None and str(nlu_data.destination_mention).strip():
        val = str(nlu_data.destination_mention).strip()
        updated.critical.destination_mention = val
        defaulted_set.discard("destination_mention")
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
        updated.extra.pinned_mentions = _merge_list_unique(updated.extra.pinned_mentions, nlu_data.pinned_mentions)
        defaulted_set.discard("pinned_mentions")

    if nlu_data.excluded_mentions:
        updated.extra.excluded_mentions = _merge_list_unique(updated.extra.excluded_mentions, nlu_data.excluded_mentions)
        defaulted_set.discard("excluded_mentions")

    if nlu_data.excluded_activities:
        updated.extra.excluded_activities = _merge_list_unique(updated.extra.excluded_activities, nlu_data.excluded_activities)
        defaulted_set.discard("excluded_activities")

    # 3. Cập nhật Hints Slots (chỉ khi chưa có destination_mention)
    if not updated.critical.destination_mention:
        if nlu_data.destination_regions:
            updated.hints.destination_regions = _merge_list_unique(updated.hints.destination_regions, nlu_data.destination_regions)
        if nlu_data.terrain_types:
            updated.hints.terrain_types = _merge_list_unique(updated.hints.terrain_types, nlu_data.terrain_types)

    # Cập nhật intent nếu NLU nhận diện intent cụ thể
    if nlu_data.intent and nlu_data.intent != "plan_itinerary":
        updated.intent = nlu_data.intent

    updated.defaulted = sorted(list(defaulted_set))
    return updated


def apply_chip_selection(
    current_request: TripRequest,
    slot_name: str,
    value: Any
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
        updated.extra.pinned_mentions = _merge_list_unique(updated.extra.pinned_mentions, [str(value).strip()])
    elif slot_name == "excluded_mentions":
        updated.extra.excluded_mentions = _merge_list_unique(updated.extra.excluded_mentions, [str(value).strip()])

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
