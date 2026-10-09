from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from typing import List
from app.services.map_service import get_static_route_image, get_multi_stop_route

router = APIRouter(prefix="/api/map", tags=["Map Service"])


class DirectionsRequest(BaseModel):
    coordinates: List[List[float]] = Field(..., min_length=2, description="Danh sách các cặp tọa độ [[lat, lng], ...]")
    vehicle: str = Field("car", description="Loại phương tiện (car, motorbike, taxi)")


@router.get("/static-route")
def get_route_map(
    origin_lat: float = Query(..., description="Vĩ độ điểm bắt đầu"),
    origin_lng: float = Query(..., description="Kinh độ điểm bắt đầu"),
    dest_lat: float = Query(..., description="Vĩ độ điểm kết thúc"),
    dest_lng: float = Query(..., description="Kinh độ điểm kết thúc"),
    vehicle: str = Query("car", description="Loại phương tiện (car, motorbike, taxi)"),
    width: int = Query(600, ge=200, le=1200),
    height: int = Query(350, ge=150, le=800)
):
    """
    Backend Proxy cung cấp ảnh bản đồ tĩnh từ Goong Map cho lộ trình di chuyển.
    Bảo vệ Goong API Key và tự động phục vụ từ cache đệm nội bộ.
    """
    image_bytes = get_static_route_image(
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        vehicle=vehicle,
        width=width,
        height=height
    )

    if not image_bytes:
        raise HTTPException(
            status_code=502,
            detail="Không thể tạo bản đồ lộ trình từ dịch vụ Goong Maps hoặc thiếu cấu hình API Key."
        )

    return Response(content=image_bytes, media_type="image/png")


@router.post("/directions")
def get_directions(req: DirectionsRequest):
    """
    Backend Proxy cung cấp đa tuyến uốn lượn đường bộ thực tế (Goong Directions API).
    Bảo vệ Goong API Key, tự động cache và giải mã tọa độ cho Leaflet vẽ đường uốn lượn thật.
    """
    coords = [(c[0], c[1]) for c in req.coordinates if len(c) >= 2]
    if len(coords) < 2:
        raise HTTPException(status_code=400, detail="Cần tối thiểu 2 điểm tọa độ hợp lệ.")

    route_data = get_multi_stop_route(coords, vehicle=req.vehicle)
    return route_data
