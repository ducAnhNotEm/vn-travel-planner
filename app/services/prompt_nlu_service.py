"""
prompt_nlu_service.py
═══════════════════════════════════════════════════════════════════════════════
Dịch vụ Phân Tích Prompt Tự Do (NLU Engine) cho Travel AI Việt Nam.
Tuân thủ Tiêu chuẩn Kỹ thuật Top 0.1% & AGENTS.md:
- Hỗ trợ GGUF v2 (vn-travel-qwen-v2: Strict Contract Invariants)
- Hỗ trợ GGUF v1 (vn-travel-qwen:7b: Rich Domain Vocabulary)
- Hỗ trợ Gộp khối (Slot-Level Fusion: Kết hợp thế mạnh V1 + V2)
- Hỗ trợ Claude 4.6 (Cloud Reference qua VyceAI)
- Phòng thủ Zero-Crash Resiliency (Không bao giờ vỡ app)
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import logging
import math
import time
import hashlib
import threading
import unicodedata
import datetime as dt
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, Tuple, List

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
NLU_CLOUD_TIMEOUT_S = float(os.getenv("NLU_CLOUD_TIMEOUT_S", "6"))
NLU_SHADOW_ENABLED = os.getenv("NLU_SHADOW_ENABLED", "0") == "1"
NLU_OLLAMA_MODEL = os.getenv("NLU_OLLAMA_MODEL", "vn-travel-qwen-v2")
NLU_AUDIT_PATH = Path(os.getenv("NLU_AUDIT_PATH", "audit_out/nlu_comparison.jsonl"))
NLU_LOG_RAW_PROMPT = os.getenv("NLU_LOG_RAW_PROMPT", "0") == "1"

logger = logging.getLogger("prompt_nlu")

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="nlu")
# Pool riêng cho shadow (Ollama có thể chiếm worker tới 75s): tránh làm đói các lệnh gọi cloud ở _POOL.
_SHADOW_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nlu-shadow")
_LOG_LOCK = threading.Lock()

SYSTEM_PROMPT = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu.\n"
    "4. 'destination' CHỈ điền khi người dùng nêu rõ một tỉnh/thành/địa danh cụ thể (chuẩn hóa về tên tỉnh/thành). Nếu người dùng chỉ nói vùng miền hoặc loại địa hình (vd: 'phía Bắc', 'đi biển', 'núi'), để destination = null và điền 'destination_regions' / 'terrain_types'. TUYỆT ĐỐI không tự liệt kê tỉnh thay cho vùng miền.\n"
    "5. 'destination_regions' chỉ nhận: NORTH, NORTHWEST, NORTHEAST, RED_RIVER_DELTA, NORTH_CENTRAL, CENTRAL, SOUTH_CENTRAL, CENTRAL_HIGHLANDS, SOUTH, SOUTHEAST, MEKONG_DELTA. 'terrain_types' chỉ nhận: BEACH, ISLAND, MOUNTAIN, HIGHLAND, FOREST, CAVE, RIVER (xếp theo bảng chữ cái). Khi đã có destination cụ thể thì cả hai để [] và các từ như 'biển', 'núi' chỉ ghi vào preferences.\n"
    "6. Địa danh người dùng muốn LOẠI TRỪ (trừ, ngoại trừ, không đi, tránh, bỏ, chán, đi rồi, khỏi...) đưa vào 'excluded_destinations' (cấp tỉnh/thành) hoặc 'excluded_places' (địa danh nhỏ hơn tỉnh). Địa danh bị loại trừ KHÔNG BAO GIỜ được đưa vào destination, hard_pinned_locations hay preferences. Điểm xuất phát (origin) độc lập với danh sách loại trừ."
)


# SYSTEM_PROMPT KHÔNG nêu tên các khóa JSON đầu ra (các model GGUF đã học schema khi fine-tune). Model cloud thì không,
# nên chỉ nhánh cloud nhận thêm khối schema này. SYSTEM_PROMPT giữ nguyên cho Ollama để không lệch phân phối huấn luyện.
CLOUD_SCHEMA_PROMPT = (
    "\nĐịnh dạng đầu ra: MỘT đối tượng JSON với ĐÚNG các khóa sau; thông tin không có thì null (hoặc [] với mảng):\n"
    '{"intent": str, "origin": str|null, "destination": str|null, "destination_regions": [str], "terrain_types": [str], '
    '"excluded_destinations": [str], "excluded_places": [str], "duration_days": int|null, "group_size": int|null, '
    '"vehicle_type": str|null, "budget_total_vnd": int|null, "prefer_flight": bool|null, "hard_pinned_locations": [str], '
    '"preferences": [str], "excluded_activities": [str]}\n'
    "Quy tắc bổ sung:\n"
    "7. 'origin' chỉ điền khi người dùng nói rõ nơi xuất phát ('từ Hà Nội', 'xuất phát ở ...'). 'Đi Đà Nẵng' KHÔNG cho biết điểm xuất phát. "
    "Nếu xuất phát từ vị trí hiện tại của người dùng ('chỗ tôi đang đứng', 'vị trí hiện tại') thì origin = \"CURRENT_LOCATION\".\n"
    "8. 'duration_days' là số ngày người dùng nói; không nói thì null, không mặc định 1.\n"
    "9. 'group_size' là số NGƯỜI đi. '7 chỗ', 'xe 16 chỗ' là loại xe, KHÔNG phải số người. Không nói thì null.\n"
    "10. 'budget_total_vnd' là tổng ngân sách quy ra số nguyên VND (vd '5 triệu' -> 5000000); không nói thì null.\n"
    "11. 'prefer_flight': true nếu muốn đi máy bay; false nếu từ chối máy bay ('không đi máy bay'); null nếu không đề cập. "
    "'vehicle_type' là phương tiện người dùng CHỌN, viết tiếng Anh chữ thường (car, motorbike, taxi, van, train, bus...) hoặc null; "
    "phương tiện bị từ chối không được ghi vào đây.\n"
    "12. Người dùng đổi ý ('không phải Đà Nẵng, tao muốn Huế'): destination là nơi muốn đi cuối cùng (Huế), nơi bị bác bỏ vào excluded_destinations.\n"
    "13. 'hard_pinned_locations' là địa danh cụ thể người dùng muốn ghé; 'preferences' là sở thích/điều kiện mong muốn "
    "(vd 'biển', 'tránh chỗ đông'); 'excluded_activities' là hoạt động muốn tránh.\n"
    "14. Câu hỏi tư vấn/kiến thức không yêu cầu lập lịch -> 'ask_advisory'; tìm/hỏi về một địa điểm cụ thể -> 'search_place'; "
    "quá thiếu thông tin để hiểu -> 'clarify_needed'.\n"
)
CLOUD_SYSTEM_PROMPT = SYSTEM_PROMPT + CLOUD_SCHEMA_PROMPT


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def extract_json_from_text(raw_text: Any) -> Optional[Dict[str, Any]]:
    """Trích xuất đối tượng JSON (dict) từ phản hồi LLM. Trả None nếu không có đối tượng hợp lệ.

    Dùng raw_decode từ từng '{' thay vì cắt từ '{' đầu tới '}' cuối: nhờ vậy văn bản có dấu ngoặc nhọn
    trước/sau JSON không làm hỏng một JSON hợp lệ. JSON bị cắt cụt vẫn trả None (không vá).
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None
    text = raw_text.strip()
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for cand in candidates:
        pos = cand.find("{")
        while pos != -1:
            try:
                obj, _ = decoder.raw_decode(cand, pos)
            except ValueError:
                pos = cand.find("{", pos + 1)
                continue
            if isinstance(obj, dict):
                return obj
            pos = cand.find("{", pos + 1)
    return None


def get_ollama_status() -> Dict[str, Any]:
    """Kiểm tra trạng thái kết nối Ollama và các models hiện có."""
    url = f"{OLLAMA_BASE_URL}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VNTravel-NLU"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "online": True,
                "url": OLLAMA_BASE_URL,
                "models": models,
                "has_v2": any(m.split(":")[0] == "vn-travel-qwen-v2" for m in models),
                "has_v1": any(m == "vn-travel-qwen:7b" for m in models),
            }
    except Exception as e:
        return {
            "online": False,
            "url": OLLAMA_BASE_URL,
            "models": [],
            "has_v2": False,
            "has_v1": False,
            "error": str(e),
        }


def call_ollama_chat(model: str, prompt: str, temperature: float = 0.0, timeout: int = 75) -> Tuple[str, float, Optional[str]]:
    """Gọi Ollama chat completion API và trả về (raw_text, latency_ms, error)."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9
        }
    }
    t0 = time.perf_counter()
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            raw_body = json.loads(resp.read().decode("utf-8"))
            content = raw_body.get("message", {}).get("content", "").strip()
            return content, dur_ms, None
    except urllib.error.HTTPError as e:
        # Server Ollama đang chạy nhưng trả lỗi HTTP (vd 404: chưa có model) -> không nói "hãy chạy ollama serve".
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, f"Ollama trả HTTP {e.code} cho model '{model}'"
    except urllib.error.URLError as e:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, f"Không thể kết nối Ollama tại {OLLAMA_BASE_URL}. Hãy chạy 'ollama serve'. Chi tiết: {e}"
    except Exception as e:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, str(e)


def call_claude_nlu(prompt: str, timeout: float = 25.0) -> Tuple[str, float, Optional[str]]:
    """Gọi Claude 4.6 (Primary Cloud) qua VyceAI API."""
    from app.services.llm_service import call_llm
    t0 = time.perf_counter()
    try:
        raw_res = call_llm(prompt=prompt, system_prompt=CLOUD_SYSTEM_PROMPT, temperature=0.0, timeout=timeout)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return raw_res, dur_ms, None
    except Exception as e:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, str(e)


# ── Canonical Slot Normalization & Diffing ──────────────────────────────────
PROVINCE_SLOTS = {"origin", "destination", "excluded_destinations"}
TEXT_PLACE_SLOTS = {"excluded_places", "hard_pinned_locations"}
INT_SLOTS = {"days", "group_size", "budget_total_vnd"}
# alias trùng khóa và trường văn bản tự do dễ lệch giả -> không tính vào discrepant_slots
IGNORED_FOR_DIFF = {"duration_days", "must_visit_places", "preferences", "excluded_activities"}

INTENT_ALIASES = {
    "plan_trip": "plan_itinerary",
    "plan_itinerary": "plan_itinerary",
    "search_place": "search_place",
    "ask_advisory": "ask_advisory",
    "clarify_needed": "clarify_needed",
}


def _canon_intent(v: Any) -> Optional[str]:
    return INTENT_ALIASES.get(str(v or "").strip().lower())


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _canon_province(s: str):
    try:
        from app.services.gazetteer import resolve_mention
        res = resolve_mention(s)
        if res and not res.get("is_ambiguous") and res.get("province_code"):
            return ("prov", int(res["province_code"]))
    except Exception as e:
        logger.debug("gazetteer không khả dụng, so khớp theo văn bản: %s", e)
    return ("txt", _strip_accents(s))


def _canon(slot: str, v: Any):
    if v in (None, "", [], {}):
        return None
    if slot == "intent":
        return _canon_intent(v)
    if isinstance(v, (list, tuple)):
        items = [_canon(slot, x) for x in v]
        return tuple(sorted((x for x in items if x is not None), key=repr)) or None
    if slot in INT_SLOTS:
        try:
            return int(float(str(v).replace(",", "").strip()))
        except (ValueError, TypeError):
            return ("txt", str(v))
    if slot == "prefer_flight":
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "có")
        return bool(v)
    if isinstance(v, str):
        if slot in PROVINCE_SLOTS:
            return _canon_province(v)
        return _strip_accents(v)
    return v


def diff_slots(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    keys = (set(a) | set(b)) - IGNORED_FOR_DIFF
    return [k for k in sorted(keys) if _canon(k, a.get(k)) != _canon(k, b.get(k))]


def _pack(engine: str, raw: str, ms: float, err: Optional[str], parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    valid = isinstance(parsed, dict) and _canon_intent(parsed.get("intent")) is not None
    if valid:
        parsed = {**parsed, "intent": _canon_intent(parsed["intent"])}
    if not err and not valid:
        err = "invalid_json_or_intent"
    return {
        "engine": engine,
        "ok": valid and not err,
        "latency_ms": round(ms, 1),
        "raw": raw,
        "parsed": parsed if valid else None,
        "extracted": _normalize_extracted_slots(parsed) if valid else {},
        "error": err,
    }


def _run_cloud(prompt: str, timeout_s: float) -> Dict[str, Any]:
    raw, ms, err = call_claude_nlu(prompt, timeout=timeout_s)
    return _pack("cloud", raw, ms, err, None if err else extract_json_from_text(raw))


def _run_ollama(prompt: str) -> Dict[str, Any]:
    raw, ms, err = call_ollama_chat(NLU_OLLAMA_MODEL, prompt)
    return _pack("ollama", raw, ms, err, None if err else extract_json_from_text(raw))


_NEG_CUES = r"(?:không|khong|ko|khg|chẳng|đừng|tránh)"
_FLIGHT_RE = re.compile(r"máy bay|may bay|vé bay|ve bay")
# phủ định + tối đa 3 từ đệm (không muốn đi máy bay / không đi bằng máy bay); dấu phẩy cắt phạm vi phủ định
_NEG_FLIGHT_RE = re.compile(_NEG_CUES + r"(?!\s+ngại)\s+(?:[^\s,;.!?]+\s+){0,3}?(?:máy bay|may bay|vé bay|ve bay)")
_DAYS_RE = re.compile(r"(\d+)\s*(?:ngày|ngay|n(?:\b|gày))")
_GROUP_RE = re.compile(r"(?:nhóm|đoàn)\s*(\d+)|(\d+)\s*(?:người|nguoi|khách|khach|thành viên|bạn|\bng\b)")
_REV_RE = re.compile(
    r"(?P<neg>(?<!\w)" + _NEG_CUES + r"\s+(?:muốn\s+)?)?(?<!\w)(?:tới|đến|đi|den|di)\s+(?P<dest>[^,;]+?)\s+"
    r"(?:xuất phát từ|khởi hành từ|xuat phat tu|khoi hanh tu|từ|tu)\s+(?P<orig>[^,;]+)", re.I)
_FWD_RE = re.compile(
    r"(?<!\w)(?:từ|tu)\s+(?P<orig>[^,;]+?)\s+(?:đi|di|đến|den|tới|sang)\s+(?P<dest>[^,;]+)", re.I)
# Chỉ cắt đuôi ở các từ nối KHÔNG xuất hiện trong tên tỉnh/địa danh ("bằng" bị loại vì có "Cao Bằng").
_STOP_RE = re.compile(r"\s+(?:cho|với|trong|vào|nhé|nhưng|rồi|khoảng|tầm|để|mà|ạ)(?!\w).*$", re.I | re.S)
_LEAD_RE = re.compile(r"^(?:du lịch|đi chơi|chơi|tham quan|thăm|nghỉ dưỡng|nghỉ mát)\s+", re.I)


def _gazetteer_confirms(text: str) -> Optional[bool]:
    """True/False nếu gazetteer xác nhận/bác bỏ cụm là địa danh; None nếu gazetteer không dùng được."""
    try:
        from app.services.gazetteer import Gazetteer, resolve_mention
        if not Gazetteer.get_instance().alias_to_code:
            # Thiếu travel_db.db -> bảng alias rỗng, resolve_mention trả None cho MỌI chuỗi (không ném lỗi).
            # Gazetteer rỗng không có quyền bác bỏ địa danh.
            return None
        res = resolve_mention(text)
    except Exception as e:
        logger.debug("gazetteer không khả dụng cho regex fallback: %s", e)
        return None
    return bool(res and (res.get("province_code") or res.get("is_ambiguous")))


def _clean_place_candidate(s: Optional[str]) -> Optional[str]:
    """Làm sạch cụm bắt được bằng regex; chỉ giữ lại nếu gazetteer không bác bỏ. Không bịa giá trị."""
    if not s:
        return None
    s = re.sub(r"\d+\s*(?:ngày|ngay|n(?:\b|gày))", " ", s, flags=re.I)
    s = re.sub(r"(?:nhóm|đoàn|đi)?\s*\d+\s*(?:người|nguoi|ng|khách|khach|bạn|thành viên)", " ", s, flags=re.I)
    s = re.sub(r"(?:đi\s+bằng|bằng)?\s*(?:máy\s*bay|may\s*bay|ô\s*tô|o\s*to|xe\s*máy|xe\s*may|tàu\s*hỏa|tau\s*hoa)", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    s = _STOP_RE.sub("", s)
    s = _LEAD_RE.sub("", s).strip(" -,")
    if not s:
        return None
    return None if _gazetteer_confirms(s) is False else s


def _run_regex_fallback(prompt: str) -> Dict[str, Any]:
    """Fallback cuối cùng, độ tin cậy THẤP: chỉ trích các slot hiển nhiên, slot không chắc để null.
    Không xác định được intent (không phân biệt được hỏi tư vấn / tìm địa điểm) nên chỉ trả
    plan_itinerary khi bắt được điểm đi/đến, ngược lại trả clarify_needed và success=False."""
    t0 = time.perf_counter()
    text = unicodedata.normalize("NFC", prompt or "")
    p_lower = text.lower()

    days = None
    m_days = _DAYS_RE.search(p_lower)
    if m_days:
        days = int(m_days.group(1)) or None

    group = None
    m_grp = _GROUP_RE.search(p_lower)
    if m_grp:
        group = int(m_grp.group(1) or m_grp.group(2)) or None

    if _NEG_FLIGHT_RE.search(p_lower):
        prefer_flight: Optional[bool] = False
    elif _FLIGHT_RE.search(p_lower):
        prefer_flight = True
    else:
        prefer_flight = None          # không đề cập != False

    origin, destination, excluded = None, None, []
    m_rev = _REV_RE.search(text)
    m_fwd = None if m_rev else _FWD_RE.search(text)
    if m_rev:
        origin = _clean_place_candidate(m_rev.group("orig"))
        dest = _clean_place_candidate(m_rev.group("dest"))
        if m_rev.group("neg"):        # "không muốn đi X từ Y": X là địa danh bị loại, không phải điểm đến
            excluded = [dest] if dest else []
        else:
            destination = dest
    elif m_fwd:
        origin = _clean_place_candidate(m_fwd.group("orig"))
        destination = _clean_place_candidate(m_fwd.group("dest"))

    parsed = {
        "intent": "plan_itinerary" if (origin or destination) else "clarify_needed",
        "origin": origin,
        "destination": destination,
        "duration_days": days,
        "group_size": group,
        "prefer_flight": prefer_flight,
        "vehicle_type": None,         # "plane" nằm ngoài tập vehicle_type của planner (car/motorbike/taxi/van); chuyến bay đã có prefer_flight
        "excluded_destinations": excluded,
    }
    has_slot = bool(origin or destination or days or group or excluded or prefer_flight is not None)
    err = None if has_slot else "regex_fallback_no_slots"
    ms = (time.perf_counter() - t0) * 1000.0
    return _pack("regex", json.dumps(parsed, ensure_ascii=False), ms, err, parsed)


def _write_audit(prompt: str, cloud: Dict[str, Any], ollama: Dict[str, Any]) -> None:
    try:
        rec = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "prompt_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest(),
            "prompt": prompt if NLU_LOG_RAW_PROMPT else None,
            "cloud": {"extracted": cloud.get("extracted", {}), "latency_ms": cloud.get("latency_ms", 0.0), "error": cloud.get("error")},
            "ollama": {"extracted": ollama.get("extracted", {}), "latency_ms": ollama.get("latency_ms", 0.0), "error": ollama.get("error")},
            "discrepant_slots": diff_slots(cloud.get("extracted", {}), ollama.get("extracted", {}))
                                if cloud.get("ok") and ollama.get("ok") else None,
            "review_status": "unreviewed",
        }
        NLU_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK, NLU_AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Không ghi được audit NLU: %s", e)


def _response(res: Dict[str, Any], chain: List[str], shadow: bool, degraded: bool = False) -> Dict[str, Any]:
    names = {"cloud": "Claude 4.6 (Cloud)", "ollama": f"Ollama ({NLU_OLLAMA_MODEL})", "regex": "Regex fallback"}
    return {
        "success": res.get("ok", False),
        "engine_used": names.get(res.get("engine", ""), res.get("engine", "")),
        "latency_ms": res.get("latency_ms", 0.0),
        "raw_response": res.get("raw", ""),
        "parsed_json": res.get("parsed"),
        "extracted": res.get("extracted", {}),
        "error": res.get("error"),
        "fallback_chain": chain,
        "shadow_enabled": shadow,
        "degraded": degraded,   # True khi kết quả đến từ regex fallback (độ tin cậy thấp)
    }


def parse_prompt_auto(prompt: str) -> Dict[str, Any]:
    cloud_f = _POOL.submit(_run_cloud, prompt, NLU_CLOUD_TIMEOUT_S)
    shadow_f = _SHADOW_POOL.submit(_run_ollama, prompt) if NLU_SHADOW_ENABLED else None

    try:
        cloud = cloud_f.result(timeout=NLU_CLOUD_TIMEOUT_S + 1)
    except Exception as e:
        cloud = _pack("cloud", "", NLU_CLOUD_TIMEOUT_S * 1000, f"deadline: {e}", None)

    if cloud["ok"]:
        if shadow_f is not None:
            shadow_f.add_done_callback(
                lambda f: _write_audit(prompt, cloud, f.result()) if not f.exception() else None
            )
        return _response(cloud, ["cloud"], NLU_SHADOW_ENABLED)

    # Cloud lỗi -> Ollama
    chain = ["cloud_failed"]
    try:
        ollama = shadow_f.result(timeout=80) if shadow_f is not None else _run_ollama(prompt)
    except Exception as e:
        ollama = _pack("ollama", "", 0.0, str(e), None)
    if shadow_f is not None:
        _write_audit(prompt, cloud, ollama)
    if ollama["ok"]:
        return _response(ollama, chain + ["ollama"], NLU_SHADOW_ENABLED)

    # Cả hai rớt -> regex fallback
    chain.append("ollama_failed")
    r_regex = _run_regex_fallback(prompt)
    return _response(r_regex, chain + ["regex"], NLU_SHADOW_ENABLED, degraded=True)


def _single_response(engine_used: str, raw: str, ms: float, err: Optional[str],
                     parsed: Optional[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    """Đường đơn engine (claude/v1/v2/fusion) dùng chung _pack với nhánh auto: cùng quy tắc hợp lệ intent/schema."""
    packed = _pack("single", raw, ms, err, None if err else parsed)
    res = {
        "success": packed["ok"],
        "engine_used": engine_used,
        "latency_ms": packed["latency_ms"],
        "raw_response": raw,
        "parsed_json": packed["parsed"],
        "extracted": packed["extracted"],
        "error": packed["error"],
    }
    res.update(extra)
    return res


_SUPPORTED_ENGINES = ("auto", "claude", "v1", "v2", "fusion")


def _first_valid_intent(*candidates: Any) -> Optional[str]:
    for c in candidates:
        if _canon_intent(c):
            return _canon_intent(c)
    return None


def parse_prompt_unified(prompt: str, engine: str = "auto") -> Dict[str, Any]:
    """
    Xử lý phân tích prompt theo mô hình được chỉ định:
    - 'auto': Cloud-first + Ollama shadow/fallback + Pure-Python regex fallback (Khuyên dùng)
    - 'v2': Ollama vn-travel-qwen-v2
    - 'v1': Ollama vn-travel-qwen:7b
    - 'fusion': Gộp khối V1 + V2 (V2 quyết định origin/destination/flight, V1 bổ sung preferences/places)
    - 'claude': Claude 4.6 Sonnet
    Engine không hỗ trợ -> success=False (không âm thầm chạy model khác).
    """
    engine = (engine or "auto").strip().lower()

    if engine not in _SUPPORTED_ENGINES:
        return _single_response(f"unsupported:{engine}", "", 0.0,
                                f"engine '{engine}' không được hỗ trợ; dùng một trong {list(_SUPPORTED_ENGINES)}", None)

    if engine == "auto":
        return parse_prompt_auto(prompt)

    if engine == "claude":
        raw, dur_ms, err = call_claude_nlu(prompt)
        return _single_response("Claude 4.6 (Cloud)", raw, dur_ms, err, extract_json_from_text(raw))

    if engine == "fusion":
        raw_v2, dur_v2, err_v2 = call_ollama_chat("vn-travel-qwen-v2", prompt, temperature=0.0)
        raw_v1, dur_v1, err_v1 = call_ollama_chat("vn-travel-qwen:7b", prompt, temperature=0.1)

        parsed_v2 = extract_json_from_text(raw_v2)
        parsed_v1 = extract_json_from_text(raw_v1)
        total_dur = dur_v2 + dur_v1

        if not parsed_v2 and not parsed_v1:
            err_msg = err_v2 or err_v1 or "Cả 2 mô hình V1 và V2 đều không trích xuất được JSON hợp lệ."
            return _single_response("Slot-Level Fusion (V1 + V2)", f"V2 Output:\n{raw_v2}\n\n---\nV1 Output:\n{raw_v1}",
                                    total_dur, err_msg, None)

        # Gộp khối (Slot-Level Fusion):
        # - V2 làm chủ: origin, destination, destination_regions, terrain_types, excluded_*, prefer_flight, vehicle_type,
        #   duration_days, budget_total_vnd
        # - V1 bổ sung: must_visit_places / hard_pinned_locations, preferences
        fused: Dict[str, Any] = {}
        fused.update(parsed_v2 or parsed_v1 or {})

        # Intent: lấy intent hợp lệ đầu tiên (V2 rồi V1); không bịa mặc định. Thiếu cả hai -> _pack báo lỗi.
        fused["intent"] = _first_valid_intent((parsed_v2 or {}).get("intent"), (parsed_v1 or {}).get("intent"))

        if parsed_v2:
            fused["origin"] = parsed_v2.get("origin")
            fused["destination"] = parsed_v2.get("destination")
            fused["destination_regions"] = parsed_v2.get("destination_regions") or []
            fused["terrain_types"] = parsed_v2.get("terrain_types") or []
            fused["excluded_destinations"] = parsed_v2.get("excluded_destinations") or []
            fused["excluded_places"] = parsed_v2.get("excluded_places") or []
            fused["prefer_flight"] = parsed_v2.get("prefer_flight")
            if parsed_v2.get("vehicle_type"):
                fused["vehicle_type"] = parsed_v2.get("vehicle_type")
            if parsed_v2.get("duration_days") or parsed_v2.get("days"):
                fused["duration_days"] = parsed_v2.get("duration_days") or parsed_v2.get("days")
                fused["days"] = fused["duration_days"]
            if parsed_v2.get("group_size"):
                fused["group_size"] = parsed_v2.get("group_size")
            if parsed_v2.get("budget_total_vnd"):
                fused["budget_total_vnd"] = parsed_v2.get("budget_total_vnd")
            if parsed_v2.get("excluded_activities"):
                fused["excluded_activities"] = parsed_v2.get("excluded_activities")

        if parsed_v1:
            places_v2 = _as_str_list((parsed_v2 or {}).get("hard_pinned_locations") or (parsed_v2 or {}).get("must_visit_places"))
            places_v1 = _as_str_list(parsed_v1.get("hard_pinned_locations") or parsed_v1.get("must_visit_places"))
            combined_places = list(dict.fromkeys(places_v2 + places_v1))
            excluded_all = {_strip_accents(x) for x in _as_str_list(fused.get("excluded_destinations")) + _as_str_list(fused.get("excluded_places"))}
            combined_places = [p for p in combined_places if _strip_accents(p) not in excluded_all]
            if combined_places:
                fused["hard_pinned_locations"] = combined_places
                fused["must_visit_places"] = combined_places

            pref_v2 = _as_str_list((parsed_v2 or {}).get("preferences"))
            pref_v1 = _as_str_list(parsed_v1.get("preferences"))
            combined_pref = list(dict.fromkeys(pref_v2 + pref_v1))
            if combined_pref:
                fused["preferences"] = combined_pref

        return _single_response("Slot-Level Fusion (V1 + V2)", json.dumps(fused, ensure_ascii=False, indent=2), total_dur, None, fused,
                                fusion_details={"v2_json": parsed_v2, "v1_json": parsed_v1, "v2_error": err_v2, "v1_error": err_v1})

    # Engine đơn lẻ: V2 hoặc V1
    model_name = "vn-travel-qwen-v2" if engine == "v2" else "vn-travel-qwen:7b"
    temp = 0.0 if engine == "v2" else 0.1
    raw, dur_ms, err = call_ollama_chat(model_name, prompt, temperature=temp)
    return _single_response(f"Ollama ({model_name})", raw, dur_ms, err, extract_json_from_text(raw))


_REGION_ENUM = {"NORTH", "NORTHWEST", "NORTHEAST", "RED_RIVER_DELTA", "NORTH_CENTRAL", "CENTRAL", "SOUTH_CENTRAL",
                "CENTRAL_HIGHLANDS", "SOUTH", "SOUTHEAST", "MEKONG_DELTA"}
_TERRAIN_ENUM = {"BEACH", "ISLAND", "MOUNTAIN", "HIGHLAND", "FOREST", "CAVE", "RIVER"}


def _as_str(v: Any) -> Optional[str]:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return None


def _as_str_list(v: Any) -> List[str]:
    """Chuỗi đơn -> [chuỗi]; kiểu lạ -> []. Không bao giờ list() một chuỗi thành các ký tự."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    elif not isinstance(v, (list, tuple, set)):
        return []
    out: List[str] = []
    for x in v:
        s = _as_str(x)
        if s and s not in out:
            out.append(s)
    return out


def _as_number(v: Any) -> Optional[float]:
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


def _as_int(v: Any, minimum: int) -> Optional[int]:
    """Số nguyên >= minimum; giá trị không hợp lệ -> None (chưa biết), không giữ chuỗi rác, không làm tròn 3.7 -> 3."""
    x = _as_number(v)
    if x is None or x != int(x) or x < minimum:
        return None
    return int(x)


def _as_bool(v: Any) -> Optional[bool]:
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


def _in_list(name: str, items: List[str]) -> bool:
    key = _strip_accents(name)
    return any(_strip_accents(x) == key for x in items)


def _normalize_extracted_slots(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Chuẩn hóa các trường cốt lõi theo Schema V3 để frontend tự động điền form và so sánh slot đồng nhất.
    Giá trị sai kiểu/ngoài tập hợp lệ -> null/[] (chưa biết). intent không hợp lệ -> None (KHÔNG mặc định plan_itinerary)."""
    d = data if isinstance(data, dict) else {}

    days = None
    for key in ("duration_days", "days", "trip_days"):
        days = _as_int(d.get(key), 1)
        if days is not None:
            break

    must_visit = _as_str_list(d.get("hard_pinned_locations") or d.get("must_visit_places"))
    excluded_destinations = _as_str_list(d.get("excluded_destinations"))
    excluded_places = _as_str_list(d.get("excluded_places"))
    destination = _as_str(d.get("destination"))

    # Mâu thuẫn nội bộ: địa danh bị loại không được là điểm đến / điểm bắt buộc (quy tắc 6 của prompt).
    if destination:
        dest_key = _canon_province(destination)
        if any(_canon_province(x) == dest_key for x in excluded_destinations) or _in_list(destination, excluded_places):
            logger.warning("NLU mâu thuẫn: destination %r nằm trong danh sách loại trừ -> destination=None", destination)
            destination = None
    excluded_all = excluded_destinations + excluded_places
    kept = [p for p in must_visit if not _in_list(p, excluded_all)]
    if len(kept) != len(must_visit):
        logger.warning("NLU mâu thuẫn: bỏ %d địa điểm bắt buộc trùng danh sách loại trừ", len(must_visit) - len(kept))
    must_visit = kept

    regions = sorted({x.strip().upper() for x in _as_str_list(d.get("destination_regions"))} & _REGION_ENUM)
    terrain = sorted({x.strip().upper() for x in _as_str_list(d.get("terrain_types"))} & _TERRAIN_ENUM)
    if destination:                    # quy tắc 5: đã có điểm đến cụ thể thì hints để []
        regions, terrain = [], []

    budget = _as_number(d.get("budget_total_vnd"))
    budget = int(budget) if budget is not None and budget > 0 else None
    vehicle = _as_str(d.get("vehicle_type"))

    return {
        "intent": _canon_intent(d.get("intent")),
        "origin": _as_str(d.get("origin")),
        "destination": destination,
        "destination_regions": regions,
        "terrain_types": terrain,
        "excluded_destinations": excluded_destinations,
        "excluded_places": excluded_places,
        "days": days,
        "duration_days": days,
        "group_size": _as_int(d.get("group_size"), 1),
        "vehicle_type": vehicle.lower() if vehicle else None,
        "budget_total_vnd": budget,
        "prefer_flight": _as_bool(d.get("prefer_flight")),
        "must_visit_places": list(must_visit),
        "hard_pinned_locations": list(must_visit),
        "preferences": _as_str_list(d.get("preferences")),
        "excluded_activities": _as_str_list(d.get("excluded_activities")),
    }
