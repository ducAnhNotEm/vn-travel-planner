"""
app/services/dialogue_engine.py
===============================================================================
Lát 2 - Bộ quy tắc hỏi làm rõ & sinh nút gợi ý (chip). Tuân thủ docs/PRODUCT_SPEC.md Mục 6, 7, 10.

Vai trò: "code đọc luật từ config/dialogue.json" (Mục 5.5) - mô hình NLU KHÔNG sinh câu hỏi.
Mọi hàm ở đây là hàm thuần túy: không ghi DB, không gọi NLU, không sửa tham số đầu vào.

    check_missing_slots(req)                 -> slot QUAN TRỌNG còn thiếu, đúng thứ tự trong config
    generate_clarification_turn(req, gaz)    -> ClarificationTurn (tối đa N câu hỏi + chip ngữ cảnh)
    apply_chip_event(req, chip)              -> TripRequest mới, ghi thẳng vào slot, BYPASS NLU
    record_turn(req, turn)                   -> TripRequest mới: cập nhật `asked` và status collecting/ready

Luồng một lượt (Mục 7.2): apply_chip_event -> generate_clarification_turn -> record_turn.
"""
import copy
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from app.dialogue_models import (
    ChipItem,
    ClarificationQuestion,
    ClarificationTurn,
    CriticalSlots,
    ExtraSlots,
    TripRequest,
)
from app.services.dialogue_state import apply_chip_selection
from app.services.gazetteer import Gazetteer, strip_accents

logger = logging.getLogger("dialogue_engine")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "dialogue.json"

CURRENT_LOCATION = "CURRENT_LOCATION"
CURRENT_LOCATION_LABEL = "Vị trí hiện tại"

CRITICAL_SLOT_NAMES = ("destination_mention", "origin_mention", "duration_days")
SUGGEST_SOURCES = ("gazetteer_by_hints", "popular_origins", "static")

# Slot mà apply_chip_selection (dialogue_state) thực sự xử lý. Slot khác sẽ bị NO-OP âm thầm ở đó,
# nên engine từ chối rõ ràng thay vì để chip "bấm mà không có tác dụng".
CHIP_SLOTS = (
    "destination_mention",
    "origin_mention",
    "duration_days",
    "group_size",
    "vehicle_type",
    "prefer_flight",
    "pinned_mentions",
    "excluded_mentions",
)

# Thành phố xuất phát phổ biến (Mục 7.3: "các thành phố lớn + CURRENT_LOCATION"), thứ tự cố định.
POPULAR_ORIGINS = ("Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ", "Huế")

REGION_LABELS = {
    "mien_bac": "miền Bắc", "tay_bac": "Tây Bắc", "dong_bac": "Đông Bắc",
    "dong_bang_song_hong": "đồng bằng sông Hồng",
    "mien_trung": "miền Trung", "bac_trung_bo": "Bắc Trung Bộ", "nam_trung_bo": "Nam Trung Bộ",
    "tay_nguyen": "Tây Nguyên",
    "mien_nam": "miền Nam", "dong_nam_bo": "Đông Nam Bộ", "tay_nam_bo": "Tây Nam Bộ",
}
TERRAIN_LABELS = {
    "nui": "núi", "bien": "biển", "dao": "đảo", "dong_bang": "đồng bằng", "cao_nguyen": "cao nguyên",
}

CONFLICT_ASK = "Điểm xuất phát và điểm đến đang trùng nhau ({place}). Quý khách muốn đi đến điểm nào khác?"

SamePlace = Callable[[str, str], bool]


# ───────────────────────────────────────────────────────────────────────────────
# Config
# ───────────────────────────────────────────────────────────────────────────────
def validate_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra cấu trúc config/dialogue.json. Lỗi cấu hình phải nổ sớm, không để chạy sai âm thầm."""
    if not isinstance(cfg, dict):
        raise ValueError("dialogue config phải là object JSON")
    mq = cfg.get("max_questions_per_turn")
    if not isinstance(mq, int) or isinstance(mq, bool) or mq < 1:
        raise ValueError("max_questions_per_turn phải là số nguyên >= 1")
    slots = cfg.get("critical_slots")
    if not isinstance(slots, list) or not slots:
        raise ValueError("critical_slots phải là danh sách không rỗng")
    seen = set()
    for item in slots:
        name = item.get("slot") if isinstance(item, dict) else None
        if name not in CRITICAL_SLOT_NAMES:
            raise ValueError(f"critical_slots: slot không hợp lệ {name!r}; hợp lệ: {CRITICAL_SLOT_NAMES}")
        if name in seen:
            raise ValueError(f"critical_slots: slot trùng {name!r}")
        seen.add(name)
        if not isinstance(item.get("ask"), str) or not item["ask"].strip():
            raise ValueError(f"critical_slots[{name}].ask phải là chuỗi không rỗng")
        sug = item.get("suggest")
        if not isinstance(sug, dict) or sug.get("source") not in SUGGEST_SOURCES:
            raise ValueError(f"critical_slots[{name}].suggest.source phải thuộc {SUGGEST_SOURCES}")
        if sug["source"] == "static" and not (isinstance(sug.get("values"), list) and sug["values"]):
            raise ValueError(f"critical_slots[{name}].suggest.values phải là danh sách không rỗng")
        lim = sug.get("limit")
        if lim is not None and (not isinstance(lim, int) or isinstance(lim, bool) or lim < 1):
            raise ValueError(f"critical_slots[{name}].suggest.limit phải là số nguyên >= 1")
    return cfg


def load_dialogue_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Đọc và kiểm tra config. Mặc định app/config/dialogue.json."""
    p = Path(path) if path else CONFIG_PATH
    with p.open("r", encoding="utf-8") as f:
        return validate_config(json.load(f))


@lru_cache(maxsize=1)
def _default_config() -> Dict[str, Any]:
    return load_dialogue_config()


def _resolve_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if config is None:
        return copy.deepcopy(_default_config())
    return validate_config(config)


# ───────────────────────────────────────────────────────────────────────────────
# Còn thiếu gì?
# ───────────────────────────────────────────────────────────────────────────────
def _slot_filled(request: TripRequest, slot: str) -> bool:
    c = request.critical
    if slot == "duration_days":
        return c.duration_days is not None and c.duration_days >= 1
    value = getattr(c, slot)
    return value is not None and bool(str(value).strip())


def check_missing_slots(trip_request: TripRequest, config: Optional[Dict[str, Any]] = None) -> List[str]:
    """
    Các slot QUAN TRỌNG còn thiếu, theo thứ tự khai báo trong config.
    - Chỉ có vùng/địa hình (hints) KHÔNG tính là có điểm đến (Mục 4.2).
    - origin_mention = "CURRENT_LOCATION" tính là đã có.
    - Slot đang dùng giá trị mặc định (`defaulted`) vẫn có giá trị nên không còn thiếu.
    - Slot `extra` không bao giờ chặn (Mục 4.1).
    """
    cfg = _resolve_config(config)
    return [s["slot"] for s in cfg["critical_slots"] if not _slot_filled(trip_request, s["slot"])]


def has_origin_destination_conflict(trip_request: TripRequest, gazetteer: Gazetteer) -> bool:
    """Điểm đến và điểm xuất phát là CÙNG MỘT thực thể (Mục 10). CURRENT_LOCATION thì không so được."""
    dest = trip_request.critical.destination_mention
    origin = trip_request.critical.origin_mention
    if not dest or not origin or origin.strip().upper() == CURRENT_LOCATION:
        return False
    return gazetteer.same_entity(dest, origin)


# ───────────────────────────────────────────────────────────────────────────────
# Sinh chip & câu hỏi
# ───────────────────────────────────────────────────────────────────────────────
_CHIP_PREFIX = {"destination_mention": "dest", "origin_mention": "orig", "duration_days": "dur"}


def _make_chip(slot: str, label: str, value: Union[bool, int, str]) -> ChipItem:
    """id ổn định theo (slot, value), vd chip_dest_sapa, chip_orig_hanoi, chip_dur_3."""
    slug = re.sub(r"[^a-z0-9]+", "", strip_accents(str(value)).lower())
    return ChipItem(id=f"chip_{_CHIP_PREFIX.get(slot, slot)}_{slug}", label=label, slot=slot, value=value)


def _region_suffix(request: TripRequest) -> str:
    """Điền {region_suffix}: ' ở miền Bắc (địa hình núi)'. Rỗng nếu không có hint."""
    regions = [REGION_LABELS.get(r, r.replace("_", " ")) for r in request.hints.destination_regions]
    terrains = [TERRAIN_LABELS.get(t, t.replace("_", " ")) for t in request.hints.terrain_types]
    suffix = ""
    if regions:
        suffix += " ở " + ", ".join(regions)
    if terrains:
        suffix += " (địa hình " + ", ".join(terrains) + ")"
    return suffix


def _destination_chips(request: TripRequest, gazetteer: Gazetteer, limit: Optional[int]) -> List[ChipItem]:
    origin = request.critical.origin_mention
    avoid = [origin] if origin and origin.strip().upper() != CURRENT_LOCATION else []
    picks = gazetteer.suggest_destinations_by_hints(
        destination_regions=request.hints.destination_regions,
        terrain_types=request.hints.terrain_types,
        limit=limit if limit is not None else 6,
        exclude=request.extra.excluded_mentions,
        avoid=avoid,
    )
    return [_make_chip("destination_mention", p["label"], p["label"]) for p in picks]


def _origin_chips(
    request: TripRequest, gazetteer: Gazetteer, limit: Optional[int], include_current: bool
) -> List[ChipItem]:
    """CURRENT_LOCATION đứng đầu; `limit` là tổng số chip (đã gồm CURRENT_LOCATION)."""
    chips: List[ChipItem] = []
    if include_current:
        chips.append(_make_chip("origin_mention", CURRENT_LOCATION_LABEL, CURRENT_LOCATION))
    dest = request.critical.destination_mention
    for city in POPULAR_ORIGINS:
        if dest and gazetteer.same_entity(city, dest):
            continue  # đừng gợi ý điểm xuất phát trùng điểm đến
        chips.append(_make_chip("origin_mention", city, city))
    return chips[:limit] if limit is not None else chips


def _static_chips(slot: str, values: List[Any], limit: Optional[int]) -> List[ChipItem]:
    chips = []
    for v in values:
        label = f"{v} ngày" if slot == "duration_days" else str(v)
        chips.append(_make_chip(slot, label, v))
    return chips[:limit] if limit is not None else chips


def _chips_for(slot_cfg: Dict[str, Any], request: TripRequest, gazetteer: Gazetteer) -> List[ChipItem]:
    slot, sug = slot_cfg["slot"], slot_cfg["suggest"]
    limit = sug.get("limit")
    if sug["source"] == "gazetteer_by_hints":
        return _destination_chips(request, gazetteer, limit)
    if sug["source"] == "popular_origins":
        return _origin_chips(request, gazetteer, limit, bool(sug.get("include_current_location")))
    return _static_chips(slot, sug["values"], limit)


def generate_clarification_turn(
    trip_request: TripRequest,
    gazetteer: Gazetteer,
    config: Optional[Dict[str, Any]] = None,
) -> ClarificationTurn:
    """
    Quyết định lượt tiếp theo (Mục 3, 6, 7, 10). KHÔNG sửa trip_request.
    - Đủ slot quan trọng và không trùng điểm đi/đến -> status "ready", không câu hỏi.
    - Ngược lại -> "collecting", tối đa `max_questions_per_turn` câu theo thứ tự config, mỗi câu kèm chip ngữ cảnh.
    - Điểm đến trùng điểm xuất phát: câu "báo và hỏi lại" về điểm đến đứng ĐẦU và chiếm một suất câu hỏi.
    """
    cfg = _resolve_config(config)
    by_slot = {s["slot"]: s for s in cfg["critical_slots"]}
    missing = check_missing_slots(trip_request, cfg)
    conflict = "destination_mention" in by_slot and has_origin_destination_conflict(trip_request, gazetteer)

    if not missing and not conflict:
        return ClarificationTurn(status="ready", questions=[], missing_slots=[], next_action=cfg.get("after_ready"))

    questions: List[ClarificationQuestion] = []
    if conflict:
        dest_cfg = by_slot["destination_mention"]
        questions.append(ClarificationQuestion(
            slot="destination_mention",
            text=CONFLICT_ASK.format(place=trip_request.critical.destination_mention),
            reason="conflict",
            chips=_chips_for(dest_cfg, trip_request, gazetteer),
        ))
    for slot in missing:
        slot_cfg = by_slot[slot]
        questions.append(ClarificationQuestion(
            slot=slot,
            text=slot_cfg["ask"].replace("{region_suffix}", _region_suffix(trip_request)),
            reason="missing",
            chips=_chips_for(slot_cfg, trip_request, gazetteer),
        ))

    return ClarificationTurn(
        status="collecting",
        questions=questions[: cfg["max_questions_per_turn"]],
        missing_slots=missing,
    )


# ───────────────────────────────────────────────────────────────────────────────
# Sự kiện chip (bypass NLU)
# ───────────────────────────────────────────────────────────────────────────────
def _parse_chip(chip: Union[ChipItem, Dict[str, Any]]):
    if isinstance(chip, ChipItem):
        return chip.slot, chip.value
    if isinstance(chip, dict):
        if "type" in chip and chip["type"] != "chip":
            raise ValueError(f"Sự kiện không phải chip: type={chip['type']!r}")
        if "slot" not in chip or "value" not in chip:
            raise ValueError("Sự kiện chip phải có 'slot' và 'value'")
        return chip["slot"], chip["value"]
    raise ValueError(f"Chip không hợp lệ: {type(chip).__name__}")


def _validate_chip_value(slot: str, value: Any) -> Any:
    """Chuẩn hóa và kiểm tra giá trị chip; sai thì ValueError (backend không tin dữ liệu frontend)."""
    if slot == "prefer_flight":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"  # bool("false") là True - phải tự đổi
        raise ValueError(f"prefer_flight cần true/false, nhận {value!r}")

    if slot in ("duration_days", "group_size"):
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{slot} cần số nguyên, nhận {value!r}")
        if isinstance(value, str):
            value = value.strip()
            if not re.fullmatch(r"\d+", value):
                raise ValueError(f"{slot} cần số nguyên, nhận {value!r}")
        # Dùng chính ràng buộc của mô hình (ge/le) để không lệch khi mô hình đổi
        model = CriticalSlots if slot == "duration_days" else ExtraSlots
        return getattr(model(**{slot: value}), slot)

    if value is None or isinstance(value, bool) or not str(value).strip():
        raise ValueError(f"{slot} cần chuỗi không rỗng, nhận {value!r}")
    text = str(value).strip()
    if slot == "origin_mention" and text.upper() == CURRENT_LOCATION:
        return CURRENT_LOCATION
    return text


def apply_chip_event(
    trip_request: TripRequest,
    chip: Union[ChipItem, Dict[str, Any]],
    same_place: Optional[SamePlace] = None,
) -> TripRequest:
    """
    Bấm chip: ghi thẳng giá trị vào slot, KHÔNG gọi NLU (Mục 7.2). Trả về bản copy mới.
    Nhận ChipItem hoặc dict sự kiện {"type": "chip", "slot": ..., "value": ...}.
    Sau hàm này caller gọi generate_clarification_turn để biết lượt tiếp theo.
    `same_place` (vd gazetteer.same_entity) cho phép gỡ loại trừ cũ khi người dùng đổi ý chọn lại địa danh đó.
    """
    slot, value = _parse_chip(chip)
    if slot not in CHIP_SLOTS:
        raise ValueError(f"Slot không hỗ trợ chip: {slot!r}; hợp lệ: {CHIP_SLOTS}")
    return apply_chip_selection(trip_request, slot, _validate_chip_value(slot, value), same_place=same_place)


def record_turn(trip_request: TripRequest, turn: ClarificationTurn) -> TripRequest:
    """
    Ghi kết quả lượt hỏi vào bản yêu cầu: thêm slot đã hỏi vào `asked` (không trùng, giữ thứ tự) và đặt
    status collecting <-> ready. Không động tới status planning/planned/error và không tăng `turn`
    (bộ điều phối hội thoại sở hữu bộ đếm lượt).
    """
    updated = trip_request.model_copy(deep=True)
    for q in turn.questions:
        if q.slot not in updated.asked:
            updated.asked.append(q.slot)
    if updated.status in ("collecting", "ready"):
        updated.status = "ready" if turn.status == "ready" else "collecting"
    return updated
