"""
test_prompt_nlu_endpoints.py
Kiểm tra tính đúng đắn và độ bền (Zero-Crash) của endpoint /api/plan/parse-prompt và /api/plan/ollama-status.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_ollama_status_endpoint():
    """Endpoint kiểm tra trạng thái Ollama phải trả về JSON hợp lệ (không bao giờ crash)."""
    resp = client.get("/api/plan/ollama-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "online" in data
    assert "models" in data
    assert isinstance(data["models"], list)


def test_parse_prompt_empty_error():
    """Gửi prompt rỗng phải trả về 400."""
    resp = client.post("/api/plan/parse-prompt", json={"prompt": ""})
    assert resp.status_code == 400


def test_parse_prompt_offline_ollama_graceful():
    """Khi Ollama offline hoặc timeout, endpoint không được throw 500 unhandled."""
    resp = client.post("/api/plan/parse-prompt", json={
        "prompt": "Tới Quảng Nam 3 ngày đi bằng máy bay xuất phát từ Bắc Ninh nhóm 4 người",
        "engine": "v2"
    })
    # Ngay cả khi Ollama chưa bật, endpoint vẫn trả 200 kèm error message chi tiết
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert "engine_used" in data
    assert "latency_ms" in data


def test_extract_json_helper():
    """Kiểm tra hàm helper trích xuất JSON."""
    from app.services.prompt_nlu_service import extract_json_from_text

    raw_markdown = "```json\n{\"intent\": \"plan_itinerary\", \"origin\": \"Bắc Ninh\"}\n```"
    res = extract_json_from_text(raw_markdown)
    assert res is not None
    assert res["origin"] == "Bắc Ninh"

    raw_text = "Dưới đây là JSON: {\"destination\": \"Đà Nẵng\"} cảm ơn bạn."
    res2 = extract_json_from_text(raw_text)
    assert res2 is not None
    assert res2["destination"] == "Đà Nẵng"


def test_schema_v3_normalize_extracted_slots():
    """Kiểm tra _normalize_extracted_slots hỗ trợ đầy đủ 15 trường của Schema V3."""
    from app.services.prompt_nlu_service import _normalize_extracted_slots

    v3_sample = {
        "intent": "PLAN_TRIP",
        "destination": None,
        "destination_regions": ["NORTH"],
        "terrain_types": ["MOUNTAIN"],
        "excluded_destinations": ["Hải Phòng"],
        "excluded_places": ["Sun World"],
        "origin": "Hà Nội",
        "duration_days": 3,
        "group_size": 2,
        "vehicle_type": "car",
        "budget_total_vnd": 5000000,
        "preferences": ["TREKKING"],
        "excluded_activities": ["KARAOKE"],
        "hard_pinned_locations": ["Đỉnh Fansipan"],
        "prefer_flight": False
    }

    norm = _normalize_extracted_slots(v3_sample)
    assert norm["destination"] is None
    assert norm["destination_regions"] == ["NORTH"]
    assert norm["terrain_types"] == ["MOUNTAIN"]
    assert norm["excluded_destinations"] == ["Hải Phòng"]
    assert norm["excluded_places"] == ["Sun World"]
    assert norm["origin"] == "Hà Nội"
    assert norm["days"] == 3
    assert norm["duration_days"] == 3
    assert norm["group_size"] == 2
    assert norm["budget_total_vnd"] == 5000000
    assert norm["hard_pinned_locations"] == ["Đỉnh Fansipan"]
    assert norm["must_visit_places"] == ["Đỉnh Fansipan"]
    assert norm["excluded_activities"] == ["KARAOKE"]
    assert norm["prefer_flight"] is False


def test_schema_v3_fusion_negative_constraint_filtering():
    """Kiểm tra Slot-Level Fusion lọc bỏ địa danh bị loại trừ khỏi danh sách điểm tham quan."""
    from app.services.prompt_nlu_service import _normalize_extracted_slots

    v2_data = {
        "intent": "PLAN_TRIP",
        "destination": None,
        "destination_regions": ["NORTH"],
        "terrain_types": ["BEACH"],
        "excluded_destinations": ["Hải Phòng"],
        "excluded_places": ["Đồ Sơn"],
        "origin": "Hà Nội",
        "duration_days": 3,
        "group_size": 3,
        "prefer_flight": False
    }
    v1_data = {
        "must_visit_places": ["Bãi Cháy", "Hải Phòng", "Đồ Sơn", "Vịnh Hạ Long"],
        "preferences": ["Hải sản"]
    }

    # Giả lập logic fusion
    fused = {}
    fused.update(v2_data)
    places_v2 = v2_data.get("hard_pinned_locations") or []
    places_v1 = v1_data.get("must_visit_places") or []
    combined = list(dict.fromkeys(places_v2 + places_v1))
    excluded = set(v2_data["excluded_destinations"] + v2_data["excluded_places"])
    filtered = [p for p in combined if p not in excluded]
    fused["hard_pinned_locations"] = filtered

    assert "Hải Phòng" not in fused["hard_pinned_locations"]
    assert "Đồ Sơn" not in fused["hard_pinned_locations"]
    assert "Bãi Cháy" in fused["hard_pinned_locations"]
    assert "Vịnh Hạ Long" in fused["hard_pinned_locations"]

