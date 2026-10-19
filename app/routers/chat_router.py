"""
app/routers/chat_router.py
===============================================================================
Lát 3 - Endpoint chat. PRODUCT_SPEC Mục 3.1, 7.2, 8. Gắn với prefix "/api/chat".

    POST /sessions                      phiên đang dở của user, hoặc tạo mới (tự cách ly phiên hỏng)
    GET  /sessions/{id}                 khôi phục aside (bản yêu cầu + lịch sử). Chỉ ĐỌC, không ghi DB.
    POST /sessions/{id}/messages        gửi chữ (qua NLU) hoặc sự kiện chip (BỎ QUA NLU)

Bảo mật: MỌI endpoint dùng Depends(get_current_user). Truy cập dữ liệu phiên luôn đi qua hàm lọc theo user
của chat_storage (get_session_for_user / get_session_messages(session_id, user_id)); phiên của user khác -> 403.

Một lượt (POST messages) - ĐÚNG ĐẮN DỰA TRÊN CAS, khoá chỉ để giảm tranh chấp:
    chữ : NLU (NGOÀI mọi khoá)
    vòng lặp tối đa MAX_COMMIT_ATTEMPTS lần:
        [khoá phiên trong tiến trình, có timeout] đọc phiên -> merge_nlu_slots / apply_chip_event
        -> generate_clarification_turn -> record_turn -> tăng `turn`
        -> (đủ slot & có planner) ĐẶT CHỖ plan_task_id, đặt status='planning'
        -> kiểm tra hợp lệ mô hình (không bao giờ ghi trạng thái sai xuống DB)
        -> commit_turn(expected_version): phiên + 2 tin nhắn trong MỘT transaction
        lệch version (StaleSessionError) -> đọc lại và tính lại, không báo lỗi cho tới khi hết số lần thử
    SAU commit, NGOÀI khoá: khởi động planner. Ý định 'planning' đã nằm trong DB TRƯỚC khi planner chạy, nên:
        - commit hỏng/lệch -> planner CHƯA chạy (không có planner mồ côi, retry không chạy planner thứ hai)
        - planner xong sớm và ghi 'planned' qua transition_session_status -> router không ghi đè được (CAS)
        - planner không khởi động được -> bù trừ: planning -> ready + tin nhắn xin lỗi (commit_turn)
Chip/giá trị sai (422) không để lại gì trong DB.

Điểm tích hợp (Depends, ghi đè được bằng app.dependency_overrides; test dùng bản giả):
    get_gazetteer()     -> đối tượng Gazetteer (same_entity, suggest_destinations_by_hints)
    get_nlu_parser()    -> callable(prompt) -> {"success": bool, "extracted": {...}}  (parse_prompt_unified)
    get_plan_starter()  -> hợp đồng planner, hai kiểu (router tự nhận biết bằng inspect.signature):
        MỚI   : callable(trip_request, user_id, plan_task_id) -> None | str
                plan_task_id do router đặt chỗ; báo lỗi bằng cách ném exception.
        CŨ    : callable(trip_request, user_id) -> Optional[str]  (trả plan_task_id; None = không khởi động)
                router gắn lại id trả về vào phiên (nếu TripRequest có trường plan_task_id).
        Mặc định CHƯA nối planner (`is_noop`): phiên dừng ở "ready".
        Worker kết thúc PHẢI ghi trạng thái bằng chat_storage.transition_session_status(id, 'planning', ...).

Mã HTTP (kèm header X-Error-Code để frontend phân biệt bằng máy):
    409 session_closed   phiên không còn 'đang dở'  -> frontend mở phiên mới (POST /sessions)
    409 session_conflict nhiều yêu cầu đua nhau và hết số lần thử -> frontend tải lại (GET) rồi gửi lại
    503 server_busy      không giành được khoá / DB đang bị khoá ghi quá lâu (kèm Retry-After)
"""
import contextlib
import inspect
import logging
import os
import sqlite3
import threading
import uuid
import zlib
from dataclasses import dataclass
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
PlanStarter = Callable[..., Optional[str]]

SESSION_NOT_FOUND = "Không tìm thấy phiên chat"
SESSION_FORBIDDEN = "Không có quyền truy cập phiên này"
SESSION_CLOSED = "Phiên chat này đã kết thúc. Hãy tạo phiên mới."
SESSION_CONFLICT = "Phiên chat vừa được cập nhật ở nơi khác. Vui lòng tải lại phiên rồi thử lại."
SESSION_CORRUPT = "Dữ liệu phiên chat bị hỏng"
SERVER_BUSY = "Hệ thống đang bận, vui lòng thử lại sau giây lát."
TURN_INVALID = "Không thể xử lý lượt hội thoại này."
NLU_FAILED_PREFIX = "Xin lỗi, tôi chưa hiểu rõ yêu cầu của quý khách. "
READY_MESSAGE = "Quý khách đã cung cấp đủ thông tin cần thiết để lên lịch trình."
PLANNING_MESSAGE = "Đã đủ thông tin. Hệ thống đang lập lịch trình cho quý khách, vui lòng chờ trong giây lát."
PLAN_START_FAILED_MESSAGE = "Chưa thể bắt đầu lập lịch trình lúc này. Quý khách vui lòng thử lại sau ít phút."

ERROR_CODE_HEADER = "X-Error-Code"
MAX_COMMIT_ATTEMPTS = 5        # số lần đọc-tính-ghi lại khi lệch version
LOCK_WAIT_SECONDS = 5.0        # chờ khoá trong tiến trình tối đa; hết hạn -> 503 (không bỏ đói threadpool)
AUTO_QUARANTINE_ENV = "CHAT_AUTO_QUARANTINE"  # "0" tắt tự cách ly phiên hỏng (vd. khi nghi deploy lỗi hàng loạt)


def _error(status: int, detail: str, code: str, headers: Optional[Dict[str, str]] = None) -> HTTPException:
    merged = {ERROR_CODE_HEADER: code}
    if headers:
        merged.update(headers)
    return HTTPException(status_code=status, detail=detail, headers=merged)


def _auto_quarantine() -> bool:
    return os.environ.get(AUTO_QUARANTINE_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


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


_no_planner.is_noop = True  # type: ignore[attr-defined]  # router không đặt status='planning' khi planner chưa nối


def get_plan_starter() -> PlanStarter:
    return _no_planner


# ───────────────────────────────────────────────────────────────────────────────
# Khoá theo phiên (chỉ GIẢM tranh chấp trong một tiến trình; tính đúng đắn do CAS trong chat_storage đảm nhiệm,
# kể cả khi nhiều worker). Có timeout để một user spam không bỏ đói threadpool; giữ khoá chỉ trong lúc
# tính + commit (mili-giây), KHÔNG giữ khi gọi planner.
# ───────────────────────────────────────────────────────────────────────────────
_LOCK_STRIPES = tuple(threading.Lock() for _ in range(64))


def _session_lock(session_id: str) -> threading.Lock:
    return _LOCK_STRIPES[zlib.crc32(session_id.encode("utf-8")) % len(_LOCK_STRIPES)]


@contextlib.contextmanager
def _session_guard(session_id: str):
    lock = _session_lock(session_id)
    if not lock.acquire(timeout=LOCK_WAIT_SECONDS):
        logger.warning("Hết thời gian chờ khoá phiên %s", session_id)
        raise _error(503, SERVER_BUSY, "server_busy", {"Retry-After": "1"})
    try:
        yield
    finally:
        lock.release()


@contextlib.contextmanager
def _db_busy_as_503():
    """DB bị khoá ghi quá DB_TIMEOUT_SECONDS -> 503 có Retry-After thay vì 500."""
    try:
        yield
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            logger.warning("DB bận: %s", exc)
            raise _error(503, SERVER_BUSY, "server_busy", {"Retry-After": "1"}) from exc
        raise


# ───────────────────────────────────────────────────────────────────────────────
# Tiện ích
# ───────────────────────────────────────────────────────────────────────────────
def _load_owned_session(session_id: str, user: UserOut) -> dict:
    """Phiên của user. Không phải của user -> 404 (không tồn tại) hoặc 403 (của người khác, theo spec).
    Muốn che sự tồn tại của phiên người khác: bỏ get_session_owner và trả 404 cho mọi trường hợp None."""
    session = chat_storage.get_session_for_user(session_id, user.id)
    if session is not None:
        return session
    if chat_storage.get_session_owner(session_id) is None:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    raise HTTPException(status_code=403, detail=SESSION_FORBIDDEN)


def _try_trip(session: dict) -> Optional[TripRequest]:
    """TripRequest hợp lệ, hoặc None nếu dữ liệu hỏng (JSON hỏng hoặc không qua mô hình). Không ghi DB."""
    if session.get("corrupt") or session.get("trip_request") is None:
        logger.error("trip_request của phiên %s là JSON hỏng", session.get("id"))
        return None
    try:
        return TripRequest.model_validate(session["trip_request"])
    except Exception:
        logger.exception("trip_request của phiên %s không qua mô hình TripRequest", session.get("id"))
        return None


def _trip_from_session(session: dict) -> TripRequest:
    """Dành cho GET và gửi tin nhắn: dữ liệu hỏng -> 500, KHÔNG sửa DB (việc cách ly chỉ nằm ở POST /sessions)."""
    trip = _try_trip(session)
    if trip is None:
        raise HTTPException(status_code=500, detail=SESSION_CORRUPT)
    return trip


def _validated(trip: TripRequest) -> TripRequest:
    """Chặn poison-pill: model_copy(update=...) KHÔNG validate nên phải kiểm lại trước khi ghi."""
    try:
        return TripRequest.model_validate(trip.model_dump(mode="json"))
    except Exception:
        logger.exception("TripRequest không hợp lệ sau khi cập nhật; từ chối ghi để không làm hỏng phiên")
        raise HTTPException(status_code=500, detail=TURN_INVALID)


def _safe_error_detail(exc: Exception) -> str:
    """Thông điệp lỗi gọn cho người dùng; không lộ tên lớp/mô hình nội bộ của pydantic."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            first = errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            return f"{loc}: {first.get('msg', 'giá trị không hợp lệ')}" if loc else str(first.get("msg", "giá trị không hợp lệ"))
        except Exception:
            pass
    return (str(exc).splitlines() or [""])[0] or "giá trị không hợp lệ"


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
# Planner: khởi động SAU commit, kèm bù trừ
# ───────────────────────────────────────────────────────────────────────────────
@dataclass
class _TurnOutcome:
    trip: TripRequest
    status: str
    bot_text: str
    chips: List[ChipItem]
    version: int                         # version của phiên SAU commit gần nhất
    reserved_plan_id: Optional[str]      # khác None = đã commit 'planning', còn nợ việc khởi động planner


def _planner_takes_reserved_id(starter: PlanStarter) -> bool:
    try:
        inspect.signature(starter).bind(None, None, None)
        return True
    except (TypeError, ValueError):
        return False


def _start_planner(starter: PlanStarter, trip: TripRequest, user_id: str, reserved_id: str) -> Optional[str]:
    """plan_task_id thực tế nếu planner đã nhận việc, None nếu không/lỗi. Kiểu MỚI: ném lỗi = thất bại,
    giá trị trả về (nếu là chuỗi) ghi đè id đặt chỗ. Kiểu CŨ: trả id; None/ném lỗi = thất bại."""
    try:
        if _planner_takes_reserved_id(starter):
            result = starter(trip, user_id, reserved_id)
            return result if isinstance(result, str) and result else reserved_id
        return starter(trip, user_id) or None
    except Exception:
        logger.exception("Không khởi động được planner (task %s)", reserved_id)
        return None


def _has_plan_task_field(trip: TripRequest) -> bool:
    return "plan_task_id" in type(trip).model_fields


def _revert_planning(session_id: str, user_id: str, outcome: _TurnOutcome) -> _TurnOutcome:
    """Planner không khởi động được: planning -> ready + tin nhắn xin lỗi (một transaction, CAS theo version)."""
    update: Dict[str, Any] = {"status": "ready"}
    if _has_plan_task_field(outcome.trip):
        update["plan_task_id"] = None
    try:
        trip = _validated(outcome.trip.model_copy(update=update))
        committed, _ = chat_storage.commit_turn(
            session_id, user_id, outcome.version, "ready", trip.model_dump(mode="json"),
            [{"role": "assistant", "content": PLAN_START_FAILED_MESSAGE, "payload": None}],
        )
    except (chat_storage.StaleSessionError, chat_storage.InvalidTransitionError, HTTPException, sqlite3.OperationalError):
        logger.exception("Không bù trừ được phiên %s sau khi planner thất bại; phiên giữ trạng thái 'planning'", session_id)
        return outcome
    return _TurnOutcome(trip=trip, status="ready", bot_text=PLAN_START_FAILED_MESSAGE, chips=[],
                        version=committed["version"], reserved_plan_id=None)


def _rebind_plan_task_id(session_id: str, user_id: str, outcome: _TurnOutcome, task_id: str) -> _TurnOutcome:
    """Planner kiểu CŨ tự sinh id khác id đặt chỗ: ghi lại id thật vào phiên (nếu mô hình có chỗ chứa)."""
    if not _has_plan_task_field(outcome.trip):
        return outcome
    try:
        trip = _validated(outcome.trip.model_copy(update={"plan_task_id": task_id}))
        committed, _ = chat_storage.commit_turn(
            session_id, user_id, outcome.version, "planning", trip.model_dump(mode="json"), [])
    except (chat_storage.StaleSessionError, chat_storage.InvalidTransitionError, HTTPException, sqlite3.OperationalError):
        logger.warning("Không gắn lại plan_task_id cho phiên %s (worker có thể đã kết thúc)", session_id)
        return outcome
    return _TurnOutcome(trip=trip, status=outcome.status, bot_text=outcome.bot_text, chips=outcome.chips,
                        version=committed["version"], reserved_plan_id=None)


def _launch_planner(session_id: str, user_id: str, plan_starter: PlanStarter,
                    outcome: _TurnOutcome) -> Tuple[_TurnOutcome, Optional[str]]:
    reserved = outcome.reserved_plan_id
    started = _start_planner(plan_starter, outcome.trip, user_id, reserved)
    if started is None:
        return _revert_planning(session_id, user_id, outcome), None
    if started != reserved:
        outcome = _rebind_plan_task_id(session_id, user_id, outcome, started)
    return outcome, started


# ───────────────────────────────────────────────────────────────────────────────
# Một lần thử của lượt chat (gọi TRONG khoá phiên)
# ───────────────────────────────────────────────────────────────────────────────
def _attempt_turn(session_id: str, user: UserOut, payload: Any, is_chip: bool, nlu_flat: Optional[NLUFlatOutput],
                  nlu_ok: bool, gazetteer: Any, planner_enabled: bool) -> Optional[_TurnOutcome]:
    """Đọc phiên, tính lượt, commit nguyên tử. Trả None nếu lệch version (người gọi đọc lại và thử tiếp)."""
    session = _load_owned_session(session_id, user)
    if session["status"] not in chat_storage.ACTIVE_STATUSES:
        raise _error(409, SESSION_CLOSED, "session_closed")
    trip = _trip_from_session(session)

    if is_chip:  # Mục 7.2: ghi thẳng vào slot, KHÔNG gọi NLU
        try:
            trip = dialogue_engine.apply_chip_event(trip, payload.model_dump(), same_place=gazetteer.same_entity)
        except ValueError as exc:  # slot không hỗ trợ / giá trị sai (gồm lỗi ràng buộc của mô hình)
            raise HTTPException(status_code=422, detail=f"Sự kiện chip không hợp lệ: {_safe_error_detail(exc)}")
        user_text = _chip_user_text(payload.slot, payload.value)
        user_payload: Optional[dict] = {"type": "chip", "slot": payload.slot, "value": payload.value}
    else:
        trip = merge_nlu_slots(trip, nlu_flat, same_place=gazetteer.same_entity)
        user_text, user_payload = payload.content, None

    turn = dialogue_engine.generate_clarification_turn(trip, gazetteer)
    trip = dialogue_engine.record_turn(trip, turn)
    trip = trip.model_copy(update={"turn": trip.turn + 1})  # record_turn không đếm lượt: router sở hữu bộ đếm

    reserved: Optional[str] = None
    if turn.status == "ready" and planner_enabled:
        reserved = uuid.uuid4().hex  # đặt chỗ id; ý định 'planning' được commit TRƯỚC khi planner chạy
        update: Dict[str, Any] = {"status": "planning"}
        if _has_plan_task_field(trip):
            update["plan_task_id"] = reserved
        trip = trip.model_copy(update=update)
    trip = _validated(trip)

    status = trip.status
    chips = _collect_chips(turn) if turn.status != "ready" else []
    bot_text = _bot_text(turn, status)
    if not nlu_ok:
        bot_text = NLU_FAILED_PREFIX + bot_text
    bot_payload = {"chips": [c.model_dump(mode="json") for c in chips]} if chips else None
    messages = [
        {"role": "user", "content": user_text, "payload": user_payload},
        {"role": "assistant", "content": bot_text, "payload": bot_payload},
    ]
    try:
        with _db_busy_as_503():
            committed, _ = chat_storage.commit_turn(
                session_id=session_id,
                user_id=user.id,
                expected_version=session["version"],
                new_status=status,
                trip_request_json=trip.model_dump(mode="json"),
                messages=messages,
            )
    except chat_storage.StaleSessionError:
        return None
    except chat_storage.InvalidTransitionError:
        raise _error(409, SESSION_CLOSED, "session_closed")
    except chat_storage.SessionNotFoundError:
        raise HTTPException(status_code=404, detail=SESSION_NOT_FOUND)
    except PermissionError:
        raise HTTPException(status_code=403, detail=SESSION_FORBIDDEN)
    return _TurnOutcome(trip=trip, status=status, bot_text=bot_text, chips=chips,
                        version=committed["version"], reserved_plan_id=reserved)


# ───────────────────────────────────────────────────────────────────────────────
# Endpoint
# ───────────────────────────────────────────────────────────────────────────────
@router.post("/sessions", response_model=CreateSessionResponse)
def create_or_resume_session(current_user: UserOut = Depends(get_current_user)):
    """Phiên đang dở ('collecting'/'ready') của user, chưa có thì tạo mới (Mục 8.1).
    Phiên đang dở bị hỏng -> cách ly (status='error', giữ nguyên dữ liệu) và mở phiên mới NGAY trong request này,
    nên F5 không bao giờ kẹt ở 500. Phiên vừa tạo mà vẫn không hợp lệ = lỗi hệ thống: dừng, không cách ly tiếp."""
    with _db_busy_as_503():
        for attempt in (0, 1):
            try:
                session = chat_storage.get_or_create_active_session(current_user.id)
            except chat_storage.UserNotFoundError:
                raise HTTPException(status_code=401, detail="phiên đăng nhập không hợp lệ hoặc đã hết hạn",
                                    headers={"WWW-Authenticate": "Bearer"})
            trip = _try_trip(session)
            if trip is not None:
                return CreateSessionResponse(session_id=session["id"], status=session["status"], trip_request=trip)
            if attempt == 0 and _auto_quarantine():
                chat_storage.quarantine_session(session["id"], current_user.id)
                logger.error("Đã cách ly phiên hỏng %s của user %s", session["id"], current_user.id)
                continue
            break
    raise HTTPException(status_code=500, detail=SESSION_CORRUPT)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, current_user: UserOut = Depends(get_current_user)):
    session = _load_owned_session(session_id, current_user)
    trip = _trip_from_session(session)
    messages = [_message_out(m) for m in chat_storage.get_session_messages(session_id, current_user.id)]
    return SessionDetailResponse(session_id=session["id"], status=session["status"], trip_request=trip,
                                 messages=messages)


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
    planner_enabled = not getattr(plan_starter, "is_noop", False)

    outcome: Optional[_TurnOutcome] = None
    for attempt in range(1, MAX_COMMIT_ATTEMPTS + 1):
        with _session_guard(session_id):
            outcome = _attempt_turn(session_id, current_user, payload, is_chip, nlu_flat, nlu_ok,
                                    gazetteer, planner_enabled)
        if outcome is not None:
            break
        logger.info("Phiên %s lệch version (lần %d/%d); đọc lại và tính lại", session_id, attempt, MAX_COMMIT_ATTEMPTS)
    if outcome is None:
        raise _error(409, SESSION_CONFLICT, "session_conflict")

    plan_task_id: Optional[str] = None
    if outcome.reserved_plan_id:  # NGOÀI khoá: planner có thể chậm
        outcome, plan_task_id = _launch_planner(session_id, current_user.id, plan_starter, outcome)

    return SendMessageResponse(
        session_id=session_id,
        status=outcome.status,
        bot_message=outcome.bot_text,
        trip_request=outcome.trip,
        chips=outcome.chips,
        is_ready=outcome.status in ("ready", "planning"),
        plan_task_id=plan_task_id if outcome.status == "planning" else None,
    )
