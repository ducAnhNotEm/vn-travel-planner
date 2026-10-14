"""
app/routers/planner_router.py
═══════════════════════════════════════════════════════════════════════════════
Nối bốn module vào một endpoint, GIỮ NGUYÊN HỢP ĐỒNG CŨ:

  place_index      -> hot-path không còn SQLite (đi qua travel_calculator đã vá; router kiểm tra sẵn sàng + /health)
  map_service      -> generate_multi_day_plan gọi plan_routes() (fan-out toàn chuyến); router nhận các DayRoute
                      để đẩy chặng chưa xong qua SSE
  advisory_stream  -> plan_id, lời khuyên AI chạy nền, GET /{plan_id}/events (SSE) và /{plan_id}/poll

TƯƠNG THÍCH NGƯỢC (frontend hiện tại không cần sửa gì)
  • Request: mọi trường cũ giữ nguyên tên/kiểu/mặc định/ràng buộc. Trường mới đều TÙY CHỌN và mặc định = hành vi cũ:
        route_wait_ms=None          -> chờ đủ mọi chặng Goong như cũ (nhưng song song)
        ai_delivery="inline"        -> include_ai_explanation=true vẫn trả text ngay trong response như cũ
        simplify_epsilon_m=0        -> polyline không bị nén
        polyline_format="array"     -> route_polyline vẫn là [[lat,lng],...]
  • Response: chỉ THÊM khóa (plan_id, advisories, stream, days[].route_status, days[].route_polyline_format).
    Không đổi/xóa khóa nào. Các trường cũ `selected_hotel_advisory.claude_ai_explanation` và
    `road_trip_feasibility.claude_ai_advisory` vẫn được điền ở chế độ inline.
  • Mã lỗi: 400 (thiếu từ khóa), 404 (không có địa điểm) như cũ; thêm 503 nếu thiếu travel_db.db.

FRONTEND MỚI (opt-in) để đạt p95 thấp:
    {"route_wait_ms": 250, "ai_delivery": "stream", "polyline_format": "encoded", "simplify_epsilon_m": 5}
    -> response trả sau ~(DB+CPU+250 ms); mở stream.events_url để nhận day_route / advisory / done.

YÊU CẦU: travel_calculator.py, llm_service.py đã áp patch (patches/*.patch). Nếu chưa vá, router tự phát hiện
và chạy chế độ cũ (không SSE cho polyline, AI inline) thay vì lỗi.
"""
import inspect
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.services import advisory_stream as ADV
from app.services import map_service, place_index
from app.services import travel_params as P
from app.services.flight_transit_service import (
    build_flight_transit_pipeline,
    enrich_plan_with_flight_transit,
    extract_destination_from_plan,
)
from app.services.polyline_codec import encode_polyline
from app.services.travel_calculator import generate_multi_day_plan

logger = logging.getLogger("planner_router")

router = APIRouter(prefix="/api/plan", tags=["Travel Planner"])
router.include_router(ADV.build_router())          # GET /api/plan/{plan_id}/events (SSE) và /poll

# calculator đã vá? (có ai_mode / route_wait_ms / route_epsilon_m)
_V2 = {"ai_mode", "route_wait_ms", "route_epsilon_m"} <= set(inspect.signature(generate_multi_day_plan).parameters)
if not _V2:
    logger.warning("travel_calculator CHƯA vá -> planner_router chạy chế độ tương thích (AI inline, không SSE polyline)")

INLINE_AI_WAIT_S = float(os.getenv("INLINE_AI_WAIT_S", "10"))   # trần chờ lời khuyên AI ở chế độ inline


class TripPlanRequest(BaseModel):
    prompt_keywords: List[str] = Field(..., description="Danh sách từ khóa tên địa điểm mong muốn ghé thăm")
    vehicle_type: str = Field("car", description="Loại phương tiện: 'car', 'motorbike', 'taxi', 'van'")
    days: int = Field(1, ge=1, le=P.MAX_TRIP_DAYS, description=f"Số ngày của chuyến đi (1 - {P.MAX_TRIP_DAYS} ngày)")
    group_size: int = Field(2, ge=1, le=20, description="Số lượng thành viên trong đoàn (1 - 20 người)")
    origin_lat: Optional[float] = Field(None, description="Vĩ độ điểm xuất phát")
    origin_lng: Optional[float] = Field(None, description="Kinh độ điểm xuất phát")
    origin_name: Optional[str] = Field("Hà Nội", description="Tên điểm xuất phát")
    prefer_flight: Optional[bool] = Field(False, description="Tùy chọn ưu tiên đi máy bay")
    drive_mode: Optional[str] = Field("express", description="Chế độ lái: 'express' (cao tốc) hoặc 'scenic' (ngắm cảnh)")
    selected_hotel_id: Optional[int] = Field(None, description="ID khách sạn khách đã chọn làm điểm neo cố định")
    include_ai_explanation: Optional[bool] = Field(False, description="Tùy chọn làm giàu lời giải thích bằng Claude 4.6")
    # ── Trường mới, TÙY CHỌN, mặc định = hành vi cũ ──────────────────────────────────────────────
    ai_delivery: Literal["inline", "stream"] = Field(
        "inline", description="'inline' (cũ): chờ lời khuyên AI rồi trả trong response. 'stream': trả ngay, AI đến qua SSE")
    route_wait_ms: Optional[int] = Field(
        None, ge=0, le=5000, description="None (cũ): chờ đủ mọi chặng Goong. N: chờ tối đa N ms, chặng chưa xong -> "
                                          "route_status='partial' và đến qua SSE (event day_route)")
    simplify_epsilon_m: float = Field(0.0, ge=0, le=100, description="Ngưỡng nén RDP (mét); 0 = giữ nguyên (cũ)")
    polyline_format: Literal["array", "encoded"] = Field(
        "array", description="'array' (cũ): [[lat,lng],...]. 'encoded': chuỗi polyline5 (nhỏ ~4x)")


# ── Cache kế hoạch: LRU có khóa. Chỉ cache khi MỌI chặng Goong là dữ liệu thật. ──────────────────
_PLAN_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_PLAN_CACHE_LOCK = threading.Lock()
_PLAN_CACHE_MAX = 200


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _PLAN_CACHE_LOCK:
        v = _PLAN_CACHE.get(key)
        if v is not None:
            _PLAN_CACHE.move_to_end(key)
        return v


def _cache_put(key: str, plan: Dict[str, Any]) -> None:
    with _PLAN_CACHE_LOCK:
        _PLAN_CACHE[key] = plan
        _PLAN_CACHE.move_to_end(key)
        while len(_PLAN_CACHE) > _PLAN_CACHE_MAX:
            _PLAN_CACHE.popitem(last=False)


def _apply_polyline_format(plan: Dict[str, Any], fmt: str) -> None:
    for d in plan.get("days", []):
        d["route_polyline_format"] = fmt
        if fmt == "encoded":
            d["route_polyline"] = encode_polyline(d.get("route_polyline") or [])


def _wait_advisories(job: ADV.PlanJob, ids: List[str], timeout_s: float) -> Dict[str, Dict[str, Any]]:
    """Chế độ inline: chờ (có trần) tới khi các lời khuyên phát sự kiện `advisory`. Chạy song song nhau ở pool nền."""
    got: Dict[str, Dict[str, Any]] = {}
    deadline = time.monotonic() + timeout_s
    while len(got) < len(ids) and time.monotonic() < deadline:
        for _, ev, data in job.events_after(-1):
            if ev == ADV.EV_ADVISORY:
                got[data["id"]] = data
        if len(got) < len(ids):
            time.sleep(0.01)
    return got


def _fallback_text(spec: Dict[str, Any]) -> str:
    try:
        from app.services import llm_service as LLM
        fb = getattr(LLM, spec.get("fallback", ""), None)
        return fb(**spec["kwargs"]) if fb else ""
    except Exception:
        return ""


@router.get("/health")
def planner_health():
    """Quan sát: chỉ mục RAM, Goong (breaker/QPS), job SSE, chế độ calculator."""
    try:
        idx = place_index.get_index().stats()
    except FileNotFoundError as e:
        idx = {"error": str(e)}
    return {"mode": "v2" if _V2 else "legacy-calculator", "place_index": idx,
            "map": map_service.stats(), "jobs": ADV.JOBS.stats(), "plan_cache": len(_PLAN_CACHE)}


@router.post("/calculate")
def calculate_plan(req: TripPlanRequest):
    """
    Tính toán lịch trình tối ưu đa ngày, gom cụm địa lý, nhịp sinh học, bản đồ tĩnh Goong Map, phân bổ chi phí
    minh bạch và tích hợp Hành trình Hàng không Khép kín + Road Trip Đường dài + lời khuyên Claude 4.6.
    """
    t0 = time.perf_counter()
    if not req.prompt_keywords:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp danh sách địa điểm cần đi.")
    try:
        place_index.get_index()                                   # fail-fast, thông điệp rõ thay vì 500 mơ hồ
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Khóa cache = nội dung kế hoạch XÁC ĐỊNH. Calculator đã vá chỉ sinh SPEC lời khuyên nên cờ AI không thuộc khóa;
    # calculator chưa vá thì text AI nằm trong plan -> cờ AI phải thuộc khóa.
    excl = {"route_wait_ms", "ai_delivery"} | (set() if _V2 else {"include_ai_explanation"})
    cache_key = json.dumps(req.model_dump(exclude=excl), sort_keys=True)
    plan = _cache_get(cache_key)
    route_jobs: list = []
    t_gen = t_enrich = 0.0

    if plan is None:
        t1 = time.perf_counter()
        if _V2:
            result = generate_multi_day_plan(
                prompt_keywords=req.prompt_keywords, days=req.days, group_size=req.group_size,
                vehicle_type=req.vehicle_type, selected_hotel_id=req.selected_hotel_id,
                include_ai_explanation=True, ai_mode="deferred",       # chỉ SINH SPEC, không gọi LLM
                route_wait_ms=req.route_wait_ms, route_epsilon_m=req.simplify_epsilon_m)
        else:
            result = generate_multi_day_plan(
                prompt_keywords=req.prompt_keywords, days=req.days, group_size=req.group_size,
                vehicle_type=req.vehicle_type, selected_hotel_id=req.selected_hotel_id,
                include_ai_explanation=bool(req.include_ai_explanation))
        t_gen = time.perf_counter() - t1
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        route_jobs = result.pop("_route_jobs", [])
        ai_jobs: List[Dict[str, Any]] = result.pop("_ai_jobs", [])

        # Xử lý tọa độ xuất phát (Tier 3 Fallback: Mặc định Hồ Gươm, Hà Nội nếu không có)
        if req.origin_lat is not None and req.origin_lng is not None:
            origin_coords = (req.origin_lat, req.origin_lng)
        else:
            origin_coords = (21.0285, 105.8542)
        origin_name = req.origin_name if req.origin_name else "Hà Nội"
        prefer_flight = bool(req.prefer_flight) if req.prefer_flight is not None else False
        drive_mode = req.drive_mode if req.drive_mode else "express"

        t2 = time.perf_counter()
        enriched_plan = enrich_plan_with_flight_transit(
            plan=result, origin_coords=origin_coords, origin_name=origin_name,
            prefer_flight=prefer_flight, vehicle_type=req.vehicle_type)
        dest_lat, dest_lng, dest_name, dest_province = extract_destination_from_plan(result)

        if "flight_transit" not in enriched_plan:
            if dest_lat is not None and dest_lng is not None:
                pipeline = build_flight_transit_pipeline(
                    origin_coords=origin_coords, dest_coords=(dest_lat, dest_lng), dest_province=dest_province,
                    origin_name=origin_name, dest_name=dest_name, group_size=req.group_size,
                    prefer_flight=prefer_flight, vehicle_type=req.vehicle_type)
                enriched_plan["flight_transit"] = pipeline.model_dump() if pipeline else {
                    "is_flight_required": False, "is_flight_applicable": False,
                    "interprovincial_distance_km": 0.0, "total_transit_cost_vnd": 0}
            else:
                enriched_plan["flight_transit"] = {
                    "is_flight_required": False, "is_flight_applicable": False,
                    "interprovincial_distance_km": 0.0, "total_transit_cost_vnd": 0}

        # ── Road Trip Engine (đường bộ đường dài) ───────────────────────────────────────────────
        if (not prefer_flight and dest_lat is not None and req.vehicle_type in ("car", "motorbike", "van")):
            try:
                from app.services.road_trip_service import (
                    _haversine, _road_distance_estimate, build_road_trip_plan, check_road_trip_feasibility)
                one_way_km = _road_distance_estimate(_haversine(origin_coords[0], origin_coords[1], dest_lat, dest_lng))
                feasibility = check_road_trip_feasibility(one_way_km, req.days, req.vehicle_type)
                if not feasibility.get("feasible") or feasibility.get("severity") == "WARNING":
                    ai_jobs.append({
                        "id": "roadtrip_tradeoff", "fn": "explain_roadtrip_tradeoff",
                        "fallback": "roadtrip_tradeoff_fallback",
                        "kwargs": dict(origin=origin_name, dest=dest_name or "điểm đến", days=req.days,
                                       needed_days=feasibility.get("min_days_recommended", req.days + 2),
                                       one_way_km=one_way_km, vehicle=req.vehicle_type)})
                enriched_plan["road_trip_feasibility"] = feasibility
                if one_way_km >= 300:
                    enriched_plan["road_trip"] = build_road_trip_plan(
                        origin_lat=origin_coords[0], origin_lng=origin_coords[1], origin_name=origin_name,
                        dest_lat=dest_lat, dest_lng=dest_lng, dest_name=dest_name,
                        vehicle=req.vehicle_type, drive_mode=drive_mode)
            except Exception:
                enriched_plan["road_trip"] = None
        t_enrich = time.perf_counter() - t2

        _apply_polyline_format(enriched_plan, req.polyline_format)
        enriched_plan["_ai_jobs"] = ai_jobs                          # private: tiền tố "_" không bao giờ serialize
        plan = enriched_plan
        if all(r.status == "complete" for r in route_jobs):          # không cache 'partial' lẫn 'degraded'
            _cache_put(cache_key, plan)

    # ── Việc nền: tạo PlanJob CHỈ khi thật sự có việc (tránh chiếm chỗ JOB_MAX/TTL vô ích) ─────────
    payload = {k: v for k, v in plan.items() if not k.startswith("_")}
    specs = plan.get("_ai_jobs", []) if req.include_ai_explanation else []
    partial = [(i, ro) for i, ro in enumerate(route_jobs, 1) if ro.status == "partial"]
    job: Optional[ADV.PlanJob] = ADV.JOBS.create() if (specs or partial) else None
    advisories: List[Dict[str, Any]] = []

    if job is not None:
        for spec in specs:
            try:
                from app.services import llm_service as LLM
                fn = getattr(LLM, spec["fn"])
            except Exception:
                continue
            advisories.append(ADV.submit_advisory(job, spec["id"], fn, spec["kwargs"], _fallback_text(spec)))
        for i, ro in partial:
            ADV.submit_route_upgrade(job, i, ro, req.simplify_epsilon_m, req.polyline_format)
        job.seal()

        if req.ai_delivery == "inline" and advisories:
            # Hành vi cũ: điền text vào các trường cũ. Sao chép-khi-ghi vì plan có thể là đối tượng trong cache.
            pend = [a["id"] for a in advisories if a["status"] == "pending"]
            done = _wait_advisories(job, pend, min(INLINE_AI_WAIT_S, ADV.AI_HARD_TIMEOUT_S + 1.0)) if pend else {}
            for a in advisories:
                d = done.get(a["id"])
                if d:
                    a.update(status="done", source=d["source"], text=d["text"])
                if a["status"] != "pending" and a["text"]:
                    if a["id"] == "hotel_tradeoff" and isinstance(payload.get("selected_hotel_advisory"), dict):
                        payload["selected_hotel_advisory"] = dict(payload["selected_hotel_advisory"],
                                                                  claude_ai_explanation=a["text"])
                    elif a["id"] == "roadtrip_tradeoff" and isinstance(payload.get("road_trip_feasibility"), dict):
                        payload["road_trip_feasibility"] = dict(payload["road_trip_feasibility"],
                                                                claude_ai_advisory=a["text"])

    has_stream = job is not None and (bool(partial) or any(a["status"] == "pending" for a in advisories))
    payload["plan_id"] = job.plan_id if has_stream else None
    payload["advisories"] = advisories
    payload["stream"] = ({"events_url": f"/api/plan/{job.plan_id}/events", "poll_url": f"/api/plan/{job.plan_id}/poll",
                          "ttl_s": int(ADV.JOB_TTL_S)} if has_stream else None)

    body = json.dumps(payload, ensure_ascii=False)
    total = time.perf_counter() - t0
    return Response(content=body, media_type="application/json", headers={
        "Server-Timing": f"gen;dur={t_gen*1000:.1f}, enrich;dur={t_enrich*1000:.1f}, total;dur={total*1000:.1f}"})


class ParsePromptRequest(BaseModel):
    prompt: str = Field(..., description="Câu yêu cầu tự do của người dùng")
    engine: Optional[str] = Field("auto", description="Mô hình NLU: 'auto', 'v2', 'v1', 'fusion', 'claude'")


@router.post("/parse-prompt")
def parse_prompt_endpoint(req: ParsePromptRequest):
    """
    Phân tích câu prompt tự do của người dùng thành cấu trúc JSON chuẩn (NLU Engine).
    Hỗ trợ so sánh giữa Ollama v2, Ollama v1, Gộp khối (Fusion) và Claude 4.6.
    """
    from app.services.prompt_nlu_service import parse_prompt_unified
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập câu prompt cần phân tích.")
    res = parse_prompt_unified(prompt=req.prompt.strip(), engine=req.engine)
    return res


@router.get("/ollama-status")
def ollama_status_endpoint():
    """Kiểm tra trạng thái máy chủ Ollama và các models hiện có."""
    from app.services.prompt_nlu_service import get_ollama_status
    return get_ollama_status()
