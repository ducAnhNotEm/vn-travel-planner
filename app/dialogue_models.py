"""
app/dialogue_models.py
===============================================================================
Mô hình dữ liệu Bản yêu cầu chuyến đi (TripRequest) và Hội thoại theo Product Spec
Tuân thủ:
- docs/PRODUCT_SPEC.md (Mục 4)
- Chỉnh sửa 1: vehicle_type mặc định là None (null).
- defaulted: ghi nhận danh sách tên các slot đang dùng giá trị mặc định để
  phân biệt rõ ràng với slot do người dùng thực sự nói ra.
"""
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, computed_field
import uuid


class CriticalSlots(BaseModel):
    destination_mention: Optional[str] = Field(None, description="Điểm đến cụ thể (POI hoặc Tỉnh/Thành)")
    origin_mention: Optional[str] = Field(None, description="Nơi xuất phát (hoặc CURRENT_LOCATION)")
    duration_days: Optional[int] = Field(None, ge=1, le=14, description="Số ngày dự kiến của chuyến đi")


class ExtraSlots(BaseModel):
    group_size: Optional[int] = Field(None, ge=1, le=50, description="Số lượng người tham gia")
    budget_total_vnd: Optional[float] = Field(None, ge=0, description="Tổng ngân sách chuyến đi (VND)")
    vehicle_type: Optional[str] = Field(None, description="Phương tiện mong muốn: car, motorbike, flight,... (mặc định null)")
    prefer_flight: Optional[bool] = Field(None, description="Ưu tiên máy bay: true/false (chưa nói = null)")
    preferences: List[str] = Field(default_factory=list, description="Sở thích du lịch: biển, ẩm thực, check-in,...")
    pinned_mentions: List[str] = Field(default_factory=list, description="Địa điểm bắt buộc ghé thăm")
    excluded_mentions: List[str] = Field(default_factory=list, description="Địa điểm muốn loại trừ")
    excluded_activities: List[str] = Field(default_factory=list, description="Hoạt động muốn loại trừ")


class HintsSlots(BaseModel):
    destination_regions: List[str] = Field(default_factory=list, description="Vùng miền manh mối: mien_bac, tay_bac,...")
    terrain_types: List[str] = Field(default_factory=list, description="Địa hình manh mối: nui, bien, dong_bang,...")


class TripRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID phiên hội thoại")
    status: Literal["collecting", "ready", "planning", "planned", "error"] = Field(
        "collecting", description="Trạng thái hội thoại"
    )
    intent: str = Field("plan_itinerary", description="Ý định hội thoại")
    critical: CriticalSlots = Field(default_factory=CriticalSlots)
    extra: ExtraSlots = Field(default_factory=ExtraSlots)
    hints: HintsSlots = Field(default_factory=HintsSlots)
    defaulted: List[str] = Field(
        default_factory=list,
        description="Danh sách các slot đang dùng giá trị mặc định (để phân biệt với user input)"
    )
    asked: List[str] = Field(default_factory=list, description="Danh sách các slot đã hỏi người dùng")
    turn: int = Field(0, ge=0, description="Số lượt tương tác hội thoại")
    plan_task_id: Optional[str] = Field(None, description="Mã tác vụ lập lịch khi ở trạng thái planning")


class NLUFlatOutput(BaseModel):
    """Schema phẳng trả về từ NLU parser"""
    intent: Optional[str] = "plan_itinerary"
    destination_mention: Optional[str] = None
    destination_regions: List[str] = Field(default_factory=list)
    terrain_types: List[str] = Field(default_factory=list)
    excluded_mentions: List[str] = Field(default_factory=list)
    origin_mention: Optional[str] = None
    duration_days: Optional[int] = None
    group_size: Optional[int] = None
    vehicle_type: Optional[str] = None
    budget_total_vnd: Optional[float] = None
    preferences: List[str] = Field(default_factory=list)
    excluded_activities: List[str] = Field(default_factory=list)
    pinned_mentions: List[str] = Field(default_factory=list)
    prefer_flight: Optional[bool] = None
    raw_query: Optional[str] = None


# ───────────────────────────────────────────────────────────────────────────────
# Lát 2: Hỏi làm rõ & nút gợi ý (chip) - PRODUCT_SPEC Mục 6, 7
# ───────────────────────────────────────────────────────────────────────────────
class ChipItem(BaseModel):
    """Một nút gợi ý. Bấm nút -> frontend gửi {"type": "chip", "slot": ..., "value": ...}."""
    id: str = Field(..., description="Định danh ổn định, vd chip_dest_sapa")
    label: str = Field(..., description="Chữ hiển thị trên nút")
    slot: str = Field(..., description="Slot sẽ được điền khi bấm, vd destination_mention")
    value: Union[bool, int, str] = Field(..., description="Giá trị ghi thẳng vào slot (không qua NLU)")


class ClarificationQuestion(BaseModel):
    slot: str = Field(..., description="Slot đang được hỏi")
    text: str = Field(..., description="Câu hỏi hiển thị cho người dùng (đọc từ config/dialogue.json)")
    reason: Literal["missing", "conflict"] = Field("missing", description="Hỏi vì thiếu slot hay vì điểm đến trùng điểm xuất phát")
    chips: List[ChipItem] = Field(default_factory=list, description="Nút gợi ý cho riêng câu hỏi này")


class ClarificationTurn(BaseModel):
    """Kết quả một lượt 'còn thiếu gì': hoặc hỏi tiếp (collecting) hoặc đủ thông tin (ready)."""
    status: Literal["collecting", "ready"]
    questions: List[ClarificationQuestion] = Field(default_factory=list, description="Tối đa max_questions_per_turn câu")
    missing_slots: List[str] = Field(default_factory=list, description="TẤT CẢ slot quan trọng còn thiếu (kể cả phần vượt giới hạn câu hỏi/lượt)")
    next_action: Optional[str] = Field(None, description="Khi ready: giá trị after_ready trong config (vd auto_plan)")

    @computed_field  # type: ignore[misc]
    @property
    def chips(self) -> List[ChipItem]:
        """Hàng nút gợi ý phẳng theo thứ tự câu hỏi (mỗi chip mang sẵn `slot`)."""
        return [c for q in self.questions for c in q.chips]
