"""
app/routers/chat_router.py
===============================================================================
Lát 3 - Bước 4: Endpoint chat. PRODUCT_SPEC Mục 3.1, 7.2, 8. Gắn với prefix "/api/chat".

    POST /sessions                      phiên đang dở của user, hoặc tạo mới
    GET  /sessions/{id}                 khôi phục aside (bản yêu cầu + lịch sử)
    POST /sessions/{id}/messages        gửi chữ (qua NLU) hoặc sự kiện chip (BỎ QUA NLU)

Bảo mật: MỌI endpoint dùng Depends(get_current_user) (401 khi chưa đăng nhập, kể cả với session không tồn tại).
Phiên của user khác -> 403 (kiểm lại lần nữa trong khoá, không tin lần kiểm đầu).

Một lượt (POST messages), thứ tự cố định:
    chữ : NLU (NGOÀI khoá, có thể chậm)  ->  [khoá phiên]  đọc lại phiên -> merge_nlu_slots
    chip: [khoá phiên]  đọc lại phiên -> apply_chip_event   (không gọi NLU)
    rồi : generate_clarification_turn -> record_turn -> tăng `turn` -> (đủ slot) khởi động planner
          -> GHI trạng thái phiên TRƯỚC, rồi ghi tin nhắn user, tin nhắn bot  [nhả khoá]
Mọi tính toán xong rồi mới ghi: chip/giá trị sai (422) không để lại gì trong DB.

Điểm tích hợp (Depends, ghi đè được bằng app.dependency_overrides; test dùng bản giả):
    get_gazetteer()     -> đối tượng Gazetteer (same_entity, suggest_destinations_by_hints)
    get_nlu_parser()    -> callable(prompt) -> {"success": bool, "extracted": {...}}  (parse_prompt_unified)
    get_plan_starter()  -> callable(trip_request, user_id) -> Optional[str] (plan_task_id)
                           Mặc định CHƯA nối planner (Mục 9, bước sau): trả None nên phiên dừng ở "ready".
"""
import logging
import threading
import zlib
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

from app.chat_models import (
    ChatMessageOut,
    ChipMessageInput,
    CreateSessionResponse,
    SendMessageInput,
    SendMessageResponse,
    SessionDetailResponse,
    TextMessageInput,
    UserOut,
)
from app.dialogue_models import ChipItem, ClarificationTurn, NLUFlatOutput, TripRequest
from app.services import chat_storage, dialogue_engine
from app.services.auth_service import get_current_user
from app.services.dialogue_state import merge_nlu_slots
from app.services.nlu_adapter import extracted_to_nlu_flat

logger = logging.getLogger("chat_router")

router = APIRouter()

NluParser = Callable[[str], Dict[str, Any]]
PlanStarter = Callable[[TripRequest, str], Optional[str]]

SESSION_NOT_FOUND = "Không tìm thấy phiên chat"
SESSION_FORBIDDEN = "Không có quyền truy cập phiên này"
SESSION_CLOSED = "Phiên chat này đã kết thúc. Hãy tạo phiên mới."
SESSION_CORRUPT = "Dữ liệu phiên chat bị hỏng"
NLU_FAILED_PREFIX = "Xin lỗi, tôi chưa hiểu rõ yêu cầu của quý khách. "
READY_MESSAGE = "Quý khách đã cung cấp đủ thông tin cần thiết để lên lịch trình."
PLANNING_MESSAGE = "Đã đủ thông tin. Hệ thống đang lập lịch trình cho quý khách, vui lòng chờ trong giây lát."


# ───────────────────────────────────────────────────────────────────────────────
# Điểm tích hợp (Depends)
# ───────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _default_gazetteer():
    # ĐIỂM TÍCH HỢP: nếu Gazetteer của dự án cần tham số khởi tạo / có hàm lấy singleton, sửa DUY NHẤT ở đây.
    from app.services import gazetteer as gazetteer_module

    factory = getattr(gazetteer_module, "get_gazetteer", None)
    return factory() if callable(factory) else gazetteer_module.Gazetteer()


def get_gazetteer():
    return _default_gazetteer()


def get_nlu_parser() -> NluParser:
    """Trả hàm bọc, import NLU ở lúc GỌI (không phải lúc dựng dependency) để sự kiện chip
    không bao giờ phụ thuộc NLU: NLU hỏng/thiếu chỉ làm hỏng lượt gõ chữ và được xử lý êm."""

    def _parse(prompt: str) -> Dict[str, Any]:
        from app.services.prompt_nlu_service import parse_prompt_unified  # ĐIỂM TÍCH HỢP

        return parse_prompt_unified(prompt)

    return _parse


def _no_planner(trip_request: TripRequest, user_id: str) -> Optional[str]:
    return None


def get_plan_starter() -> PlanStarter:
    return _no_planner


# ───────────────────────────────────────────────────────────────────────────────
# Khoá theo phiên: tuần tự hoá đọc-sửa-ghi trong một tiến trình (chống bấm đúp / gửi song song làm mất slot).
# 64 khoá băm theo session_id: bộ nhớ cố định. Nhiều worker cần khoá ở mức DB (ngoài phạm vi bước này).
# ───────────────────────────────────────────────────────────────────────────────
_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


def _session_lock(session_id: str) -> threading.Lock:
    return _LOCK_STRIPES[zlib.crc32(session_id.encode("utf-8")) % len(_LOCK_STRIPES)]


# ───────────────────────────────────────────────────────────────────────────────
# Tiện ích
# ───────────────────────────────────────────────────────────────────────────────
def _load_owned_session(session_id: str, user: UserOut) -> dict:
    session = chat_storage.get_session_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    if session["user_id"] != user.id:
        raise HTTPException(status_code=403, detail=SESSION_FORBIDDEN)
    return session


def _trip_from_session(session: dict) -> TripRequest:
    try:
        return TripRequest.model_validate(session["trip_request"])
    except ValueError:
        logger.exception("trip_request của phiên %s không hợp lệ", session.get("id"))
        raise HTTPException(status_code=500, detail=SESSION_CORRUPT)


def _message_out(message: dict) -> ChatMessageOut:
    payload = message.get("payload")
    chips = payload.get("chips") if isinstance(payload, dict) else None
    fields = dict(id=message["id"], session_id=message["session_id"], role=message["role"],
                  content=message["content"], created_at=message["created_at"])
    try:
        return ChatMessageOut(**fields, chips=chips or [])
    except (ValueError, TypeError):
        logger.warning("payload chip của tin nhắn %s không hợp lệ -> bỏ chip", message.get("id"))
        return ChatMessageOut(**fields, chips=[])


def _run_nlu(parser: NluParser, text: str) -> Tuple[NLUFlatOutput, bool]:
    """NLU hỏng KHÔNG làm hỏng lượt: coi như không trích được slot nào, vẫn hỏi tiếp. Trả (kết quả, thành_công)."""
    try:
        result = parser(text)
    except Exception:
        logger.exception("NLU ném lỗi")
        return extracted_to_nlu_flat(None, raw_query=text), False
    if isinstance(result, dict) and result.get("success"):
        return extracted_to_nlu_flat(result.get("extracted"), raw_query=text), True
    logger.warning("NLU không thành công: %r", result if not isinstance(result, dict) else result.get("error"))
    return extracted_to_nlu_flat(None, raw_query=text), False


def _chip_user_text(slot: str, value: Any) -> str:
    """Nội dung tin nhắn của người dùng khi bấm chip (Mục 7.2: 'hiện lựa chọn như một tin nhắn')."""
    if slot == "duration_days":
        return f"{str(value).strip()} ngày"
    if slot == "origin_mention" and str(value).strip().upper() == dialogue_engine.CURRENT_LOCATION:
        return dialogue_engine.CURRENT_LOCATION_LABEL
    if isinstance(value, bool):
        return "Có" if value else "Không"
    return str(value).strip()


def _collect_chips(turn: ClarificationTurn) -> List[ChipItem]:
    chips: List[ChipItem] = []
    seen = set()
    for question in turn.questions:
        for chip in question.chips:
            if chip.id not in seen:
                seen.add(chip.id)
                chips.append(chip)
    return chips


def _bot_text(turn: ClarificationTurn, status: str) -> str:
    if turn.status == "ready":
        return PLANNING_MESSAGE if status == "planning" else READY_MESSAGE
    return " ".join(q.text for q in turn.questions)


# ───────────────────────────────────────────────────────────────────────────────
# Endpoint
# ───────────────────────────────────────────────────────────────────────────────
@router.post("/sessions", response_model=CreateSessionResponse)
def create_or_resume_session(current_user: UserOut = Depends(get_current_user)):
    """Phiên đang dở ('collecting'/'ready') của user, chưa có thì tạo mới (Mục 8.1)."""
    try:
        session = chat_storage.get_or_create_active_session(current_user.id)
    except chat_storage.UserNotFoundError:
        raise HTTPException(status_code=401, detail="phiên đăng nhập không hợp lệ hoặc đã hết hạn",
                            headers={"WWW-Authenticate": "Bearer"})
    return CreateSessionResponse(session_id=session["id"], status=session["status"],
                                 trip_request=_trip_from_session(session))


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, current_user: UserOut = Depends(get_current_user)):
    session = _load_owned_session(session_id, current_user)
    messages = [_message_out(m) for m in chat_storage.get_session_messages(session_id)]
    return SessionDetailResponse(session_id=session["id"], status=session["status"],
                                 trip_request=_trip_from_session(session), messages=messages)


@router.post("/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(
    session_id: str,
    payload: SendMessageInput,
    current_user: UserOut = Depends(get_current_user),
    gazetteer=Depends(get_gazetteer),
    nlu_parser: NluParser = Depends(get_nlu_parser),
    plan_starter: PlanStarter = Depends(get_plan_starter),
):
    _load_owned_session(session_id, current_user)  # từ chối sớm (404/403) trước khi tốn công NLU

    is_chip = isinstance(payload, ChipMessageInput)
    nlu_flat, nlu_ok = (None, True) if is_chip else _run_nlu(nlu_parser, payload.content)

    with _session_lock(session_id):
        # Đọc lại TRONG khoá: trạng thái có thể đã đổi trong lúc NLU chạy hoặc do yêu cầu song song.
        session = _load_owned_session(session_id, current_user)
        if session["status"] not in chat_storage.ACTIVE_STATUSES:
            raise HTTPException(status_code=409, detail=SESSION_CLOSED)
        trip = _trip_from_session(session)

        if is_chip:  # Mục 7.2: ghi thẳng vào slot, KHÔNG gọi NLU
            try:
                trip = dialogue_engine.apply_chip_event(trip, payload.model_dump(), same_place=gazetteer.same_entity)
            except ValueError as exc:  # slot không hỗ trợ / giá trị sai (gồm lỗi ràng buộc của mô hình)
                detail = (str(exc).splitlines() or ["giá trị không hợp lệ"])[0]
                raise HTTPException(status_code=422, detail=f"Sự kiện chip không hợp lệ: {detail}")
            user_text = _chip_user_text(payload.slot, payload.value)
            user_payload: Optional[dict] = {"type": "chip", "slot": payload.slot, "value": payload.value}
        else:
            trip = merge_nlu_slots(trip, nlu_flat, same_place=gazetteer.same_entity)
            user_text, user_payload = payload.content, None

        turn = dialogue_engine.generate_clarification_turn(trip, gazetteer)
        trip = dialogue_engine.record_turn(trip, turn)
        trip = trip.model_copy(update={"turn": trip.turn + 1})  # record_turn không đếm lượt: router sở hữu bộ đếm

        plan_task_id: Optional[str] = None
        if turn.status == "ready":
            try:
                plan_task_id = plan_starter(trip, current_user.id)
            except Exception:
                logger.exception("Không khởi động được planner cho phiên %s; giữ trạng thái 'ready'", session_id)
            if plan_task_id:
                update: Dict[str, Any] = {"status": "planning"}
                if "plan_task_id" in type(trip).model_fields:
                    update["plan_task_id"] = plan_task_id
                trip = trip.model_copy(update=update)

        status = trip.status
        chips = _collect_chips(turn) if turn.status != "ready" else []
        bot_text = _bot_text(turn, status)
        if not nlu_ok:
            bot_text = NLU_FAILED_PREFIX + bot_text
        bot_payload = {"chips": [c.model_dump(mode="json") for c in chips]} if chips else None

        # Trạng thái phiên là nguồn sự thật: ghi trước, rồi tới hai tin nhắn (user trước, bot sau).
        chat_storage.update_session_trip_request(session_id, trip.model_dump(mode="json"), status)
        chat_storage.add_chat_message(session_id, "user", user_text, user_payload)
        chat_storage.add_chat_message(session_id, "assistant", bot_text, bot_payload)

    return SendMessageResponse(
        session_id=session_id,
        status=status,
        bot_message=bot_text,
        trip_request=trip,
        chips=chips,
        is_ready=status in ("ready", "planning"),
        plan_task_id=plan_task_id if status == "planning" else None,
    )
