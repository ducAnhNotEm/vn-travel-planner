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
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple, List

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

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


def call_claude_nlu(prompt: str) -> Tuple[str, float, Optional[str]]:
    """Gọi Claude 4.6 (Primary Cloud) qua VyceAI API."""
    from app.services.llm_service import call_llm
    t0 = time.perf_counter()
    try:
        raw_res = call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0, timeout=25)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return raw_res, dur_ms, None
    except Exception as e:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, str(e)


def parse_prompt_unified(prompt: str, engine: str = "v2") -> Dict[str, Any]:
    """
    Xử lý phân tích prompt theo mô hình được chỉ định:
    - 'v2': Ollama vn-travel-qwen-v2
    - 'v1': Ollama vn-travel-qwen:7b
    - 'fusion': Gộp khối V1 + V2 (V2 quyết định origin/destination/flight, V1 bổ sung preferences/places)
    - 'claude': Claude 4.6 Sonnet
    """
    engine = (engine or "v2").lower()

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
    """Chuẩn hóa các trường cốt lõi theo Schema V3 để frontend tự động điền form và hiển thị badges."""
    if not data:
        return {}
    
    days = data.get("duration_days") or data.get("days") or data.get("trip_days")
    must_visit = data.get("hard_pinned_locations") or data.get("must_visit_places") or []

    return {
        "intent": data.get("intent", "PLAN_TRIP"),
        "origin": data.get("origin"),
        "destination": data.get("destination"),
        "destination_regions": data.get("destination_regions") or [],
        "terrain_types": data.get("terrain_types") or [],
        "excluded_destinations": data.get("excluded_destinations") or [],
        "excluded_places": data.get("excluded_places") or [],
        "days": days,
        "duration_days": days,
        "group_size": data.get("group_size"),
        "vehicle_type": data.get("vehicle_type"),
        "budget_total_vnd": data.get("budget_total_vnd"),
        "prefer_flight": data.get("prefer_flight"),
        "must_visit_places": must_visit,
        "hard_pinned_locations": must_visit,
        "preferences": data.get("preferences") or [],
        "excluded_activities": data.get("excluded_activities") or [],
    }

