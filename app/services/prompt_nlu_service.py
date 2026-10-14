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

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="nlu")
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


def extract_json_from_text(raw_text: str) -> Optional[Dict[str, Any]]:
    """Trích xuất và làm sạch chuỗi JSON từ phản hồi LLM."""
    if not raw_text:
        return None
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx + 1]
        try:
            return json.loads(json_str)
        except Exception:
            return None
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
                "has_v2": any("v2" in m for m in models),
                "has_v1": any("vn-travel-qwen:7b" in m or ("qwen" in m and "v2" not in m) for m in models),
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
        raw_res = call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0, timeout=timeout)
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
    except Exception:
        pass
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


def _run_regex_fallback(prompt: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    p_lower = prompt.lower()

    days = None
    m_days = re.search(r'(\d+)\s*(?:ngày|ngay|n(?:\b|gày))', p_lower)
    if m_days:
        try:
            days = int(m_days.group(1))
        except (ValueError, TypeError):
            pass

    group = None
    m_grp = re.search(r'(?:nhóm|đoàn)\s*(\d+)|(\d+)\s*(?:người|khách|thành viên|bạn|\bng\b)', p_lower)
    if m_grp:
        try:
            val = m_grp.group(1) or m_grp.group(2)
            group = int(val)
        except (ValueError, TypeError):
            pass

    has_flight = bool(re.search(r'máy bay|may bay|vé bay', p_lower))
    neg_flight = bool(re.search(r'(?:không|chẳng|ko|khg|đừng)\s*(?:đi|chọn)?\s*(?:máy bay|may bay)', p_lower))
    prefer_flight = True if (has_flight and not neg_flight) else False

    origin, destination = None, None
    m_rev = re.search(r'(?:tới|đến|đi)\s+([^,]+?)\s+(?:xuất phát từ|khởi hành từ|từ)\s+([^,]+)', prompt, re.I)
    m_fwd = re.search(r'từ\s+([^,]+?)\s+(?:đi|đến|tới|sang)\s+([^,]+)', prompt, re.I)

    def _clean_cand(s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        s = re.sub(r'\d+\s*(?:ngày|ngay|n(?:\b|gày))', ' ', s, flags=re.I)
        s = re.sub(r'(?:đi\s+bằng|bằng)?\s*(?:máy\s*bay|ô\s*tô|xe\s*máy|tàu\s*hỏa)', ' ', s, flags=re.I)
        s = re.sub(r'(?:nhóm|đoàn|đi)?\s*\d+\s*(?:người|ng|khách|bạn|thành viên)', ' ', s, flags=re.I)
        s = re.sub(r'\s+', ' ', s).strip()
        return s or None

    if m_rev:
        destination = _clean_cand(m_rev.group(1))
        origin = _clean_cand(m_rev.group(2))
    elif m_fwd:
        origin = _clean_cand(m_fwd.group(1))
        destination = _clean_cand(m_fwd.group(2))

    parsed = {
        "intent": "plan_itinerary",
        "origin": origin,
        "destination": destination,
        "duration_days": days,
        "group_size": group,
        "prefer_flight": prefer_flight,
        "vehicle_type": "plane" if prefer_flight else None,
    }
    ms = (time.perf_counter() - t0) * 1000.0
    return _pack("regex", json.dumps(parsed, ensure_ascii=False), ms, None, parsed)


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
    except Exception:
        pass


def _response(res: Dict[str, Any], chain: List[str], shadow: bool) -> Dict[str, Any]:
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
    }


def parse_prompt_auto(prompt: str) -> Dict[str, Any]:
    cloud_f = _POOL.submit(_run_cloud, prompt, NLU_CLOUD_TIMEOUT_S)
    shadow_f = _POOL.submit(_run_ollama, prompt) if NLU_SHADOW_ENABLED else None

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
    return _response(r_regex, chain + ["regex"], NLU_SHADOW_ENABLED)


def parse_prompt_unified(prompt: str, engine: str = "auto") -> Dict[str, Any]:
    """
    Xử lý phân tích prompt theo mô hình được chỉ định:
    - 'auto': Cloud-first + Ollama shadow/fallback + Pure-Python regex fallback (Khuyên dùng)
    - 'v2': Ollama vn-travel-qwen-v2
    - 'v1': Ollama vn-travel-qwen:7b
    - 'fusion': Gộp khối V1 + V2 (V2 quyết định origin/destination/flight, V1 bổ sung preferences/places)
    - 'claude': Claude 4.6 Sonnet
    """
    engine = (engine or "auto").lower()

    if engine == "auto":
        return parse_prompt_auto(prompt)

    if engine == "claude":
        raw, dur_ms, err = call_claude_nlu(prompt)
        parsed = extract_json_from_text(raw)
        return {
            "success": parsed is not None,
            "engine_used": "Claude 4.6 (Cloud)",
            "latency_ms": round(dur_ms, 1),
            "raw_response": raw,
            "parsed_json": parsed,
            "extracted": _normalize_extracted_slots(parsed) if parsed else {},
            "error": err,
        }

    elif engine == "fusion":
        # Gọi cả 2 model V2 và V1
        raw_v2, dur_v2, err_v2 = call_ollama_chat("vn-travel-qwen-v2", prompt, temperature=0.0)
        raw_v1, dur_v1, err_v1 = call_ollama_chat("vn-travel-qwen:7b", prompt, temperature=0.1)

        parsed_v2 = extract_json_from_text(raw_v2)
        parsed_v1 = extract_json_from_text(raw_v1)

        total_dur = dur_v2 + dur_v1

        if not parsed_v2 and not parsed_v1:
            err_msg = err_v2 or err_v1 or "Cả 2 mô hình V1 và V2 đều không trích xuất được JSON hợp lệ."
            return {
                "success": False,
                "engine_used": "Slot-Level Fusion (V1 + V2)",
                "latency_ms": round(total_dur, 1),
                "raw_response": f"V2 Output:\n{raw_v2}\n\n---\nV1 Output:\n{raw_v1}",
                "parsed_json": None,
                "extracted": {},
                "error": err_msg,
            }

        # Gộp khối thông minh (Slot-Level Fusion):
        # - V2 làm chủ: origin, destination, destination_regions, terrain_types, excluded_destinations,
        #   excluded_places, prefer_flight, vehicle_type, duration_days, budget_total_vnd
        # - V1 bổ sung: must_visit_places / hard_pinned_locations, preferences
        fused: Dict[str, Any] = {}
        base = parsed_v2 or parsed_v1 or {}
        fused.update(base)

        if parsed_v2:
            fused["intent"] = parsed_v2.get("intent", "PLAN_TRIP")
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
            # Hợp nhất danh sách must_visit_places / hard_pinned_locations
            places_v2 = (parsed_v2.get("hard_pinned_locations") or parsed_v2.get("must_visit_places") or []) if parsed_v2 else []
            places_v1 = parsed_v1.get("hard_pinned_locations") or parsed_v1.get("must_visit_places") or []
            combined_places = list(dict.fromkeys(places_v2 + places_v1))
            # Lọc bỏ các điểm trùng với excluded_destinations hoặc excluded_places
            excluded_all = set((fused.get("excluded_destinations") or []) + (fused.get("excluded_places") or []))
            combined_places = [p for p in combined_places if p not in excluded_all]
            if combined_places:
                fused["hard_pinned_locations"] = combined_places
                fused["must_visit_places"] = combined_places

            # Hợp nhất preferences
            pref_v2 = (parsed_v2.get("preferences") or []) if parsed_v2 else []
            pref_v1 = parsed_v1.get("preferences") or []
            combined_pref = list(dict.fromkeys(pref_v2 + pref_v1))
            if combined_pref:
                fused["preferences"] = combined_pref

        return {
            "success": True,
            "engine_used": "Slot-Level Fusion (V1 + V2)",
            "latency_ms": round(total_dur, 1),
            "raw_response": json.dumps(fused, ensure_ascii=False, indent=2),
            "parsed_json": fused,
            "fusion_details": {
                "v2_json": parsed_v2,
                "v1_json": parsed_v1,
            },
            "extracted": _normalize_extracted_slots(fused),
            "error": None,
        }

    else:
        # Engine đơn lẻ: V2 hoặc V1
        model_name = "vn-travel-qwen-v2" if engine == "v2" else "vn-travel-qwen:7b"
        temp = 0.0 if engine == "v2" else 0.1
        raw, dur_ms, err = call_ollama_chat(model_name, prompt, temperature=temp)
        parsed = extract_json_from_text(raw)

        return {
            "success": parsed is not None,
            "engine_used": f"Ollama ({model_name})",
            "latency_ms": round(dur_ms, 1),
            "raw_response": raw,
            "parsed_json": parsed,
            "extracted": _normalize_extracted_slots(parsed) if parsed else {},
            "error": err,
        }


def _normalize_extracted_slots(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Chuẩn hóa các trường cốt lõi theo Schema V3 để frontend tự động điền form và so sánh slot đồng nhất."""
    d = data or {}
    raw_intent = _canon_intent(d.get("intent")) or str(d.get("intent") or "plan_itinerary").lower()

    days = d.get("duration_days") or d.get("days") or d.get("trip_days")
    if days is not None:
        try:
            days = int(float(str(days).replace(",", "").strip()))
        except (ValueError, TypeError):
            pass

    group_size = d.get("group_size")
    if group_size is not None:
        try:
            group_size = int(float(str(group_size).replace(",", "").strip()))
        except (ValueError, TypeError):
            pass

    budget = d.get("budget_total_vnd")
    if budget is not None:
        try:
            budget = int(float(str(budget).replace(",", "").strip()))
        except (ValueError, TypeError):
            pass

    must_visit = d.get("hard_pinned_locations") or d.get("must_visit_places") or []
    if isinstance(must_visit, str):
        must_visit = [must_visit]

    prefer_flight = d.get("prefer_flight")
    if isinstance(prefer_flight, str):
        prefer_flight = prefer_flight.strip().lower() in ("true", "1", "yes", "có")
    elif prefer_flight is not None:
        prefer_flight = bool(prefer_flight)

    return {
        "intent": raw_intent,
        "origin": d.get("origin") or None,
        "destination": d.get("destination") or None,
        "destination_regions": list(d.get("destination_regions") or []),
        "terrain_types": list(d.get("terrain_types") or []),
        "excluded_destinations": list(d.get("excluded_destinations") or []),
        "excluded_places": list(d.get("excluded_places") or []),
        "days": days,
        "duration_days": days,
        "group_size": group_size,
        "vehicle_type": d.get("vehicle_type") or None,
        "budget_total_vnd": budget,
        "prefer_flight": prefer_flight,
        "must_visit_places": list(must_visit),
        "hard_pinned_locations": list(must_visit),
        "preferences": list(d.get("preferences") or []),
        "excluded_activities": list(d.get("excluded_activities") or []),
    }

