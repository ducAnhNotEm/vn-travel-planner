from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from app.services.travel_calculator import generate_multi_day_plan
from app.services.flight_transit_service import (
    enrich_plan_with_flight_transit,
    build_flight_transit_pipeline,
    extract_destination_from_plan
)

router = APIRouter(prefix="/api/plan", tags=["Travel Planner"])

class TripPlanRequest(BaseModel):
    prompt_keywords: List[str] = Field(..., description="Danh sách từ khóa tên địa điểm mong muốn ghé thăm")
    vehicle_type: str = Field("car", description="Loại phương tiện: 'car', 'motorbike', 'taxi', 'van'")
    days: int = Field(1, ge=1, le=5, description="Số ngày của chuyến đi (1 - 5 ngày)")
    group_size: int = Field(2, ge=1, le=20, description="Số lượng thành viên trong đoàn (1 - 20 người)")
    origin_lat: Optional[float] = Field(None, description="Vĩ độ điểm xuất phát")
    origin_lng: Optional[float] = Field(None, description="Kinh độ điểm xuất phát")
    origin_name: Optional[str] = Field("Hà Nội", description="Tên điểm xuất phát")
    prefer_flight: Optional[bool] = Field(False, description="Tùy chọn ưu tiên đi máy bay")
    drive_mode: Optional[str] = Field("express", description="Chế độ lái: 'express' (cao tốc) hoặc 'scenic' (ngắm cảnh)")

@router.post("/calculate")
def calculate_plan(req: TripPlanRequest):
    """
    Tính toán lịch trình tối ưu đa ngày, gom cụm địa lý, nhịp sinh học,
    bản đồ tĩnh Goong Map, phân bổ chi phí minh bạch và tích hợp
    Hành trình Hàng không Khép kín (Door-to-Door Flight Transit Pipeline)
    và Road Trip Đường dài (Fatigue-Constraint Road Trip Engine).
    """
    if not req.prompt_keywords:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp danh sách địa điểm cần đi.")

    result = generate_multi_day_plan(
        prompt_keywords=req.prompt_keywords,
        days=req.days,
        group_size=req.group_size,
        vehicle_type=req.vehicle_type
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    # Xử lý tọa độ xuất phát (Tier 3 Fallback: Mặc định Hồ Gươm, Hà Nội nếu không có)
    if req.origin_lat is not None and req.origin_lng is not None:
        origin_coords = (req.origin_lat, req.origin_lng)
    else:
        origin_coords = (21.0285, 105.8542)

    origin_name   = req.origin_name if req.origin_name else "Hà Nội"
    prefer_flight = bool(req.prefer_flight) if req.prefer_flight is not None else False
    drive_mode    = req.drive_mode if req.drive_mode else "express"

    # Tích hợp dịch vụ hành trình hàng không khép kín
    enriched_plan = enrich_plan_with_flight_transit(
        plan=result,
        origin_coords=origin_coords,
        origin_name=origin_name,
        prefer_flight=prefer_flight,
        vehicle_type=req.vehicle_type
    )

    # Đảm bảo metadata flight_transit luôn hiện diện ở root (kể cả cự ly ngắn < 300km)
    dest_lat, dest_lng, dest_name, dest_province = extract_destination_from_plan(result)

    if "flight_transit" not in enriched_plan:
        if dest_lat is not None and dest_lng is not None:
            pipeline = build_flight_transit_pipeline(
                origin_coords=origin_coords,
                dest_coords=(dest_lat, dest_lng),
                dest_province=dest_province,
                origin_name=origin_name,
                dest_name=dest_name,
                group_size=req.group_size,
                prefer_flight=prefer_flight,
                vehicle_type=req.vehicle_type
            )
            enriched_plan["flight_transit"] = pipeline.model_dump() if pipeline else {
                "is_flight_required": False, "is_flight_applicable": False,
                "interprovincial_distance_km": 0.0, "total_transit_cost_vnd": 0
            }
        else:
            enriched_plan["flight_transit"] = {
                "is_flight_required": False, "is_flight_applicable": False,
                "interprovincial_distance_km": 0.0, "total_transit_cost_vnd": 0
            }

    # ── Tích hợp Road Trip Engine (khi đi đường bộ đường dài) ────────────────
    # Điều kiện: Không ưu tiên máy bay VÀ có tọa độ đích VÀ xe là road vehicle
    if (not prefer_flight
            and dest_lat is not None
            and req.vehicle_type in ("car", "motorbike", "van")):
        try:
            from app.services.road_trip_service import (
                build_road_trip_plan, check_road_trip_feasibility,
                _road_distance_estimate, _haversine
            )
            one_way_km = _road_distance_estimate(
                _haversine(origin_coords[0], origin_coords[1], dest_lat, dest_lng)
            )
            feasibility = check_road_trip_feasibility(one_way_km, req.days, req.vehicle_type)
            enriched_plan["road_trip_feasibility"] = feasibility

            # Chỉ build full road trip plan khi cự ly đủ lớn (>= 300km)
            if one_way_km >= 300:
                road_trip = build_road_trip_plan(
                    origin_lat=origin_coords[0], origin_lng=origin_coords[1],
                    origin_name=origin_name,
                    dest_lat=dest_lat, dest_lng=dest_lng,
                    dest_name=dest_name,
                    vehicle=req.vehicle_type,
                    drive_mode=drive_mode,
                )
                enriched_plan["road_trip"] = road_trip
        except Exception:
            # Defensive: Road trip engine failure không làm vỡ response chính
            enriched_plan["road_trip"] = None

    return enriched_plan
