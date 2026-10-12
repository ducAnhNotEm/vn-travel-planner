"""
tests/test_dialogue_state.py
===============================================================================
Unit tests cho Dialogue State Reducer (Lát 1)
Kiểm tra toàn diện 100% các yêu cầu của docs/PRODUCT_SPEC.md (Mục 4, 5, 10, 12):
1. Khởi tạo mặc định: vehicle_type = None, critical rỗng, defaulted rỗng.
2. Quy tắc 1: Slot mới ghi vào, slot null/[] KHÔNG ghi đè giá trị cũ.
3. Quy tắc 2: Đổi ý (overwrite) giá trị cũ.
4. Quy tắc 3: Danh sách gộp và loại trùng.
5. Quy tắc 4: Khi destination_mention xuất hiện thì xóa hints.
6. Quy tắc 5 (Chỉnh sửa 1 của User): Slot defaulted được ghi nhận, và nếu user tự nói thì loại khỏi defaulted.
7. Xử lý sự kiện chip trực tiếp (apply_chip_selection).
"""
import pytest
from app.dialogue_models import TripRequest, NLUFlatOutput
from app.services.dialogue_state import (
    merge_nlu_slots,
    apply_chip_selection,
    apply_default_slot,
)


def test_initial_state_defaults():
    """Kiểm tra khởi tạo ban đầu tuân thủ đúng spec & Chỉnh sửa 1 của User"""
    req = TripRequest()
    assert req.status == "collecting"
    assert req.critical.destination_mention is None
    assert req.critical.origin_mention is None
    assert req.critical.duration_days is None
    # Chỉnh sửa 1: vehicle_type giữ null, không tự gán "car"
    assert req.extra.vehicle_type is None
    assert req.extra.group_size is None
    assert req.extra.budget_total_vnd is None
    assert req.defaulted == []
    assert req.turn == 0


def test_rule_1_merge_no_overwrite_with_null():
    """Quy tắc 1: Slot mới có giá trị thì ghi vào, slot null không ghi đè giá trị cũ"""
    req = TripRequest()
    # Turn 1: user nói điểm đến
    nlu_1 = NLUFlatOutput(destination_mention="Đà Nẵng")
    req = merge_nlu_slots(req, nlu_1)
    assert req.critical.destination_mention == "Đà Nẵng"

    # Turn 2: user chỉ nói điểm xuất phát ("từ Hà Nội"), destination_mention trong NLU là None
    nlu_2 = NLUFlatOutput(origin_mention="Hà Nội", destination_mention=None)
    req = merge_nlu_slots(req, nlu_2)
    assert req.critical.destination_mention == "Đà Nẵng"  # Không bị xóa
    assert req.critical.origin_mention == "Hà Nội"


def test_rule_2_user_changes_mind_overwrites():
    """Quy tắc 2: Người dùng đổi ý thì giá trị mới ghi đè giá trị cũ"""
    req = TripRequest()
    req = merge_nlu_slots(req, NLUFlatOutput(destination_mention="Đà Nẵng", duration_days=3))
    assert req.critical.destination_mention == "Đà Nẵng"
    assert req.critical.duration_days == 3

    # Đổi ý sang Sa Pa 4 ngày
    req = merge_nlu_slots(req, NLUFlatOutput(destination_mention="Sa Pa", duration_days=4))
    assert req.critical.destination_mention == "Sa Pa"
    assert req.critical.duration_days == 4


def test_rule_3_list_merging_and_deduplication():
    """Quy tắc 3: Danh sách gộp và loại trùng lặp"""
    req = TripRequest()
    nlu_1 = NLUFlatOutput(
        preferences=["tắm biển", "ẩm thực"],
        pinned_mentions=["Bà Nà Hills"],
        excluded_mentions=["Bán đảo Sơn Trà"]
    )
    req = merge_nlu_slots(req, nlu_1)

    nlu_2 = NLUFlatOutput(
        preferences=["ẩm thực", "ngắm hoàng hôn"],
        pinned_mentions=["Bà Nà Hills", "Cầu Rồng"],
        excluded_mentions=["Ngũ Hành Sơn"]
    )
    req = merge_nlu_slots(req, nlu_2)

    assert req.extra.preferences == ["tắm biển", "ẩm thực", "ngắm hoàng hôn"]
    assert req.extra.pinned_mentions == ["Bà Nà Hills", "Cầu Rồng"]
    assert req.extra.excluded_mentions == ["Bán đảo Sơn Trà", "Ngũ Hành Sơn"]


def test_rule_4_destination_clears_hints():
    """Quy tắc 4: Khi destination_mention có giá trị thì xóa hints (vùng, địa hình)"""
    req = TripRequest()
    # Ban đầu user nói chung chung: "du lịch miền núi phía bắc"
    nlu_hint = NLUFlatOutput(
        destination_regions=["mien_bac"],
        terrain_types=["nui"]
    )
    req = merge_nlu_slots(req, nlu_hint)
    assert req.critical.destination_mention is None
    assert req.hints.destination_regions == ["mien_bac"]
    assert req.hints.terrain_types == ["nui"]

    # Sau đó chọn cụ thể "Sa Pa"
    nlu_dest = NLUFlatOutput(destination_mention="Sa Pa")
    req = merge_nlu_slots(req, nlu_dest)
    assert req.critical.destination_mention == "Sa Pa"
    # Hints phải bị dọn sạch
    assert req.hints.destination_regions == []
    assert req.hints.terrain_types == []


def test_rule_5_defaulted_tracking_and_override():
    """
    Quy tắc 5: Theo dõi defaulted slots và xóa khỏi defaulted khi user tự cung cấp.
    Đúng yêu cầu chỉnh sửa 1 của User.
    """
    req = TripRequest()
    # Giả định hệ thống điền mặc định group_size = 2 sau khi hỏi mà khách không trả lời
    req = apply_default_slot(req, "group_size", 2)
    assert req.extra.group_size == 2
    assert "group_size" in req.defaulted

    # Người dùng sau đó nói: "Đi đoàn 5 người"
    req = merge_nlu_slots(req, NLUFlatOutput(group_size=5))
    assert req.extra.group_size == 5
    # Slot không còn coi là defaulted nữa
    assert "group_size" not in req.defaulted


def test_chip_selection_bypass_nlu():
    """Kiểm tra áp dụng nút gợi ý (chip) trực tiếp"""
    req = TripRequest()
    req = merge_nlu_slots(req, NLUFlatOutput(destination_regions=["tay_bac"]))
    assert req.hints.destination_regions == ["tay_bac"]

    # Bấm chip Sa Pa
    req = apply_chip_selection(req, "destination_mention", "Sa Pa")
    assert req.critical.destination_mention == "Sa Pa"
    assert req.hints.destination_regions == []

    # Bấm chip số ngày 3
    req = apply_chip_selection(req, "duration_days", 3)
    assert req.critical.duration_days == 3

    # Bấm chip xuất phát Hà Nội
    req = apply_chip_selection(req, "origin_mention", "Hà Nội")
    assert req.critical.origin_mention == "Hà Nội"


def test_dict_input_support():
    """Hỗ trợ cả dict raw payload đầu vào cho merge_nlu_slots"""
    req = TripRequest()
    payload = {
        "destination_mention": "Hội An",
        "origin_mention": "Đà Nẵng",
        "duration_days": 2,
        "prefer_flight": False
    }
    req = merge_nlu_slots(req, payload)
    assert req.critical.destination_mention == "Hội An"
    assert req.critical.origin_mention == "Đà Nẵng"
    assert req.critical.duration_days == 2
    assert req.extra.prefer_flight is False
