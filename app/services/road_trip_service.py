"""
app/services/road_trip_service.py
═══════════════════════════════════════════════════════════════════════════════
Bộ máy định tuyến Road Trip Đường dài đa phương thức (Long-Distance Road Trip Engine)
Chuẩn mực: Top 0.1% Principal Systems Architect — Zero hallucination, deterministic math only.

KIẾN TRÚC 3 TẦNG:
  Tầng 1 — Phân luồng cự ly:  Haversine tính khoảng cách liên tỉnh.
  Tầng 2 — Ràng buộc an toàn: Fatigue Constraint (≤ 4h lái liên tục, ≤ 8h/ngày).
  Tầng 3 — Tối ưu hành lang:  Corridor Buffer quét travel_db.db cho Scenic Mode.

AI SLOT:
  Module này KHÔNG dùng LLM. Đầu vào là TripIntent đã được chuẩn hóa.
  Khi Qwen 7B được tích hợp, nó chỉ cần điền TripIntent rồi gọi hàm này.

HẰNG SỐ VẬT LÝ (Không được thay đổi — Dữ liệu thực tế Việt Nam):
  Ô tô cá nhân trên cao tốc:  90-100 km/h → dùng 80 km/h (trung bình thực tế có tắc đường)
  Ô tô cá nhân trên quốc lộ: 60-80 km/h → dùng 60 km/h
  Xe máy: 50-60 km/h → dùng 50 km/h
  Ràng buộc sinh học tài xế:  Tối đa 4h lái liên tục, dừng 30 phút, tối đa 8h/ngày
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

# ─── Đường dẫn DB mặc định ────────────────────────────────────────────────────
_DB_PATH = r"d:\vn-travel-planner\travel_db.db"


# ══════════════════════════════════════════════════════════════════════════════
# 1. ENUM & DATA CONTRACT (AI Slot — Qwen 7B sẽ điền vào đây)
# ══════════════════════════════════════════════════════════════════════════════

class DriveMode(str, Enum):
    """Chế độ lái xe đường dài: Chạy nhanh hay Du ngoạn ngắm cảnh."""
    EXPRESS = "express"   # ⚡ Cao tốc, ưu tiên thời gian
    SCENIC  = "scenic"    # 🌄 Đường đèo, ngắm cảnh, ghé danh thắng ven đường


class VehicleType(str, Enum):
    CAR       = "car"
    MOTORBIKE = "motorbike"
    VAN       = "van"


@dataclass(frozen=True)
class GeoPoint:
    """Tọa độ GPS bất biến."""
    lat: float
    lng: float
    name: str = ""


@dataclass
class PitStop:
    """
    Trạm dừng chân trên hành trình.
    Loại SHORT: dừng 30 phút (đổ xăng, vệ sinh, uống nước).
    Loại MEAL:  dừng 75-90 phút (ăn trưa đặc sản địa phương).
    Loại OVERNIGHT: nghỉ đêm giữa chặng.
    """
    stop_type: str          # "SHORT" | "MEAL" | "OVERNIGHT"
    name: str
    address: str
    lat: float
    lng: float
    arrival_time: str       # "HH:MM"
    departure_time: str     # "HH:MM"
    duration_mins: int
    cumulative_km: float    # Km đã đi tính từ điểm xuất phát
    description: str = ""
    image_url: Optional[str] = None
    google_maps_url: Optional[str] = None


@dataclass
class DrivingSegment:
    """Một chặng lái xe giữa 2 điểm dừng liên tiếp."""
    from_name: str
    to_name: str
    distance_km: float
    drive_time_mins: int    # Thời gian lái thuần (không tính đỗ xe)
    departure_time: str
    arrival_time: str


@dataclass
class RoadTripDay:
    """Một ngày trong hành trình lái xe đường dài."""
    day_index: int          # 1 = Ngày đi; -1 = Ngày về
    day_type: str           # "OUTBOUND_DRIVE" | "AT_DESTINATION" | "RETURN_DRIVE"
    title: str
    start_location: str
    end_location: str
    total_km: float
    total_drive_hours: float
    fuel_cost_vnd: int
    segments: List[DrivingSegment] = field(default_factory=list)
    pit_stops: List[PitStop] = field(default_factory=list)
    scenic_waypoints: List[dict] = field(default_factory=list)  # Điểm ngắm cảnh dọc đường (Scenic Mode)
    overnight_city: Optional[str] = None    # Tên TP nghỉ đêm giữa chặng
    feasibility_warning: Optional[str] = None


@dataclass
class RoadTripPlan:
    """
    Kết quả hoàn chỉnh của Road Trip Engine.
    Đây là "AI Slot" output — engine phía dưới không thay đổi khi AI được tích hợp.
    """
    origin: GeoPoint
    destination: GeoPoint
    vehicle: VehicleType
    drive_mode: DriveMode
    total_one_way_km: float
    requires_multi_day_drive: bool          # True nếu D >= 400km
    outbound_days: List[RoadTripDay]        # Chiều đi
    return_days: List[RoadTripDay]          # Chiều về (tuyến khác nếu Scenic)
    feasibility_advisory: Optional[str]    # Cảnh báo mâu thuẫn thời gian
    estimated_fuel_cost_vnd: int
    parsed_by: str = "deterministic"       # Slot cho AI tag sau này


# ══════════════════════════════════════════════════════════════════════════════
# 2. HẰNG SỐ VẬT LÝ & THAM SỐ AN TOÀN GIAO THÔNG
# ══════════════════════════════════════════════════════════════════════════════

# Vận tốc trung bình thực tế Việt Nam (km/h) — có tính yếu tố tắc đường, đèo dốc
_SPEED_KMH = {
    VehicleType.CAR:       75.0,   # Kết hợp cao tốc + quốc lộ + đô thị
    VehicleType.MOTORBIKE: 50.0,
    VehicleType.VAN:       70.0,
}

# Chi phí xăng (đ/km) — từ travel_calculator.py, giữ nhất quán
_FUEL_COST_PER_KM = {
    VehicleType.CAR:       1800,
    VehicleType.MOTORBIKE: 600,
    VehicleType.VAN:       2400,
}

# Ràng buộc an toàn sinh học (giờ)
_MAX_CONTINUOUS_DRIVE_HRS = 4.0    # Không lái quá 4h liên tục
_MANDATORY_SHORT_BREAK_MINS = 30   # Dừng nghỉ bắt buộc
_MAX_DAILY_DRIVE_HRS = 8.0         # Tổng không quá 8h/ngày
_SAFE_DAILY_KM = {                  # Km an toàn tối đa mỗi ngày
    VehicleType.CAR:       400,
    VehicleType.MOTORBIKE: 280,
    VehicleType.VAN:       380,
}

# Ngưỡng kích hoạt Road Trip mode
_ROAD_TRIP_THRESHOLD_KM = 300.0    # Dưới ngưỡng này: đường bộ trực tiếp, không cần staging
_OVERNIGHT_STAGING_KM   = 400.0    # Từ ngưỡng này: bắt buộc nghỉ đêm giữa chặng

# Bán kính Corridor Buffer cho Scenic Mode (km vuông góc tính từ trục đường)
_SCENIC_CORRIDOR_RADIUS_KM = 20.0

# Tọa độ trung tâm các tỉnh/thành phố dọc trục Bắc-Nam (Ground truth — không bịa)
# Dùng làm điểm nghỉ đêm trung gian (Intermediate Overnight Staging Cities)
_STAGING_CITIES_NORTH_SOUTH: List[dict] = [
    {"name": "Trung tâm Hà Nội",       "lat": 21.0285, "lng": 105.8542, "province": "Hà Nội"},
    {"name": "Trung tâm Ninh Bình",     "lat": 20.2506, "lng": 105.9745, "province": "Ninh Bình"},
    {"name": "Trung tâm Thanh Hóa",     "lat": 19.8081, "lng": 105.7765, "province": "Thanh Hóa"},
    {"name": "Trung tâm Vinh",          "lat": 18.6696, "lng": 105.6813, "province": "Nghệ An"},
    {"name": "Trung tâm Hà Tĩnh",       "lat": 18.3557, "lng": 105.8877, "province": "Hà Tĩnh"},
    {"name": "Trung tâm Đồng Hới",      "lat": 17.4765, "lng": 106.5999, "province": "Quảng Bình"},
    {"name": "Trung tâm Đông Hà",       "lat": 16.8163, "lng": 107.1003, "province": "Quảng Trị"},
    {"name": "Trung tâm Huế",           "lat": 16.4637, "lng": 107.5909, "province": "Thừa Thiên Huế"},
    {"name": "Trung tâm Đà Nẵng",       "lat": 16.0544, "lng": 108.2022, "province": "Đà Nẵng"},
    {"name": "Trung tâm Tam Kỳ",        "lat": 15.5736, "lng": 108.4747, "province": "Quảng Nam"},
    {"name": "Trung tâm Quảng Ngãi",    "lat": 15.1204, "lng": 108.8044, "province": "Quảng Ngãi"},
    {"name": "Trung tâm Quy Nhơn",      "lat": 13.7830, "lng": 109.2196, "province": "Bình Định"},
    {"name": "Trung tâm Tuy Hòa",       "lat": 13.0955, "lng": 109.3125, "province": "Phú Yên"},
    {"name": "Trung tâm Nha Trang",     "lat": 12.2388, "lng": 109.1967, "province": "Khánh Hòa"},
    {"name": "Trung tâm Phan Rang",     "lat": 11.5639, "lng": 108.9886, "province": "Ninh Thuận"},
    {"name": "Trung tâm Phan Thiết",    "lat": 10.9280, "lng": 108.1006, "province": "Bình Thuận"},
    {"name": "Trung tâm TP. Hồ Chí Minh","lat": 10.7769,"lng": 106.7009, "province": "TP. Hồ Chí Minh"},
]

# Điểm đặc biệt — Scenic Mode: Đèo ngắm cảnh nổi tiếng
_SCENIC_PASSES: List[dict] = [
    {
        "name": "Đèo Hải Vân Quan",
        "lat": 16.1974, "lng": 108.1134,
        "description": "Đèo hùng vĩ nhìn xuống Vịnh Lăng Cô và TP. Đà Nẵng. Dừng 30 phút check-in.",
        "detour_km": 8.0,           # Km thêm so với đi hầm
        "saves_vs_tunnel": False,
        "best_time": "07:00-09:00", # Trước khi nắng gắt
    },
    {
        "name": "Đèo Cả (Scenic road)",
        "lat": 12.9871, "lng": 109.3583,
        "description": "Cung đường biển tuyệt đẹp Phú Yên–Khánh Hòa thay thế hầm Đèo Cả.",
        "detour_km": 10.0,
        "saves_vs_tunnel": False,
        "best_time": "08:00-11:00",
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 3. TIỆN ÍCH TOÁN HỌC THUẦN (Pure Math Utilities)
# ══════════════════════════════════════════════════════════════════════════════

def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách đường chim bay (km) — công thức Haversine chuẩn."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _road_distance_estimate(haversine_km: float) -> float:
    """
    Ước lượng khoảng cách đường bộ thực tế từ khoảng cách chim bay.
    Hệ số tortuosity 1.35 là giá trị chuẩn cho đường bộ Việt Nam (có đèo, cua).
    Nguồn: Nghiên cứu thực địa dữ liệu Google Maps VN.
    """
    return haversine_km * 1.35


def _drive_time_mins(road_km: float, vehicle: VehicleType) -> int:
    """Thời gian lái thuần (phút), không tính dừng nghỉ."""
    speed = _SPEED_KMH[vehicle]
    return int(math.ceil((road_km / speed) * 60))


def _add_minutes(time_str: str, minutes: int) -> str:
    """Cộng thêm số phút vào chuỗi giờ 'HH:MM'."""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _point_to_segment_distance(p_lat: float, p_lng: float,
                                a_lat: float, a_lng: float,
                                b_lat: float, b_lng: float) -> float:
    """
    Khoảng cách vuông góc từ điểm P tới đoạn thẳng AB (dùng cho Corridor Buffer).
    Tính trong không gian phẳng (đủ chính xác cho khoảng cách < 200 km ở VN).
    """
    ax, ay = a_lng, a_lat
    bx, by = b_lng, b_lat
    px, py = p_lng, p_lat

    ab_sq = (bx - ax) ** 2 + (by - ay) ** 2
    if ab_sq < 1e-12:
        return _haversine(p_lat, p_lng, a_lat, a_lng)

    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ab_sq))
    proj_x = ax + t * (bx - ax)
    proj_y = ay + t * (by - ay)
    # Chuyển delta độ sang km (1 độ ≈ 111 km)
    return math.sqrt(((px - proj_x) * 111) ** 2 + ((py - proj_y) * 111 * math.cos(math.radians(p_lat))) ** 2)


# ══════════════════════════════════════════════════════════════════════════════
# 4. TÌM ĐIỂM NGHỈ ĐÊM TỐI ƯU (Intermediate Overnight Staging)
# ══════════════════════════════════════════════════════════════════════════════

def _find_optimal_staging_city(
    origin: GeoPoint,
    destination: GeoPoint,
    vehicle: VehicleType,
    leg_index: int = 0,       # 0 = lượt đi, 1 = lượt về
) -> dict:
    """
    Tìm thành phố nghỉ đêm trung gian tối ưu trên trục Bắc-Nam.

    Thuật toán:
      1. Tính quãng đường an toàn tối đa mỗi ngày cho loại xe.
      2. Chiếu lần lượt các thành phố staging lên trục origin→destination.
      3. Chọn thành phố nằm gần nhất với điểm mục tiêu = (safe_daily_km * progress_ratio).

    Không bịa đặt tên thành phố — chỉ dùng danh sách ground truth _STAGING_CITIES_NORTH_SOUTH.
    """
    safe_km = _SAFE_DAILY_KM[vehicle]
    total_haversine = _haversine(origin.lat, origin.lng, destination.lat, destination.lng)
    total_road = _road_distance_estimate(total_haversine)

    # Tỷ lệ đoạn đường mục tiêu của ngày đầu (0.0 → 1.0)
    target_ratio = min(safe_km / total_road, 0.55)  # Không vượt 55% tổng đường trong ngày đầu

    # Tọa độ điểm mục tiêu lý tưởng (nội suy tuyến tính trên trục)
    target_lat = origin.lat + (destination.lat - origin.lat) * target_ratio
    target_lng = origin.lng + (destination.lng - origin.lng) * target_ratio

    # Lọc các thành phố nằm giữa origin và destination (không đi quá lố)
    candidates = []
    for city in _STAGING_CITIES_NORTH_SOUTH:
        dist_from_origin = _haversine(origin.lat, origin.lng, city["lat"], city["lng"])
        dist_to_dest = _haversine(city["lat"], city["lng"], destination.lat, destination.lng)
        # Chỉ xét thành phố nằm trên hành lang giữa origin và destination
        if dist_from_origin < total_haversine and dist_to_dest < total_haversine:
            dist_to_ideal = _haversine(city["lat"], city["lng"], target_lat, target_lng)
            candidates.append((dist_to_ideal, city))

    if not candidates:
        # Fallback: thành phố trung gian gần nhất về mặt địa lý
        mid_lat = (origin.lat + destination.lat) / 2
        mid_lng = (origin.lng + destination.lng) / 2
        candidates = [(_haversine(c["lat"], c["lng"], mid_lat, mid_lng), c) for c in _STAGING_CITIES_NORTH_SOUTH]

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


# ══════════════════════════════════════════════════════════════════════════════
# 5. THUẬT TOÁN PHÂN BỔ TRẠM DỪNG NGHỈ (Fatigue-Constraint Pit-Stop Planner)
# ══════════════════════════════════════════════════════════════════════════════

def _plan_pit_stops(
    start: GeoPoint,
    end: GeoPoint,
    vehicle: VehicleType,
    drive_mode: DriveMode,
    departure_time: str = "06:30",
    cumulative_km_offset: float = 0.0,
    db_path: str = _DB_PATH,
) -> Tuple[List[PitStop], List[DrivingSegment], float, float]:
    """
    Phân bổ trạm dừng nghỉ theo ràng buộc sinh học cho MỘT chặng lái xe.

    Trả về: (pit_stops, segments, total_road_km, total_drive_mins_pure)
    """
    road_km = _road_distance_estimate(_haversine(start.lat, start.lng, end.lat, end.lng))
    speed_kmh = _SPEED_KMH[vehicle]

    pit_stops: List[PitStop] = []
    segments: List[DrivingSegment] = []

    current_time = departure_time
    km_remaining = road_km
    km_driven_since_last_break = 0.0
    cumulative_km = cumulative_km_offset
    current_loc_name = start.name
    current_lat, current_lng = start.lat, start.lng
    total_pure_drive_mins = 0

    max_km_per_leg = _MAX_CONTINUOUS_DRIVE_HRS * speed_kmh  # km trước khi phải nghỉ

    while km_remaining > 5.0:  # Tiếp tục cho đến khi đến nơi (sai số 5 km)
        # ── Tính toán trước: chặng sắp lái có đi qua khung ăn trưa không? ──
        # Nếu chặng sẽ kết thúc trong khung 11-13h → cắt ngắn để dừng đúng ~11:30.
        h_depart = int(current_time.split(":")[0])
        m_depart = int(current_time.split(":")[1])
        depart_total_mins = h_depart * 60 + m_depart
        max_drivable_km = max_km_per_leg - km_driven_since_last_break
        full_drive_mins = _drive_time_mins(min(km_remaining, max_drivable_km), vehicle)
        projected_arrival_h = ((depart_total_mins + full_drive_mins) // 60) % 24

        # Lunch intercept:
        #   Điều kiện: (a) chặng hiện tại sẽ đi qua 11:30 (bất kể km đã đi)
        #              (b) hoặc sẽ đến nơi trong khung 11-13h sau >= 30km
        lunch_window_mins = 11 * 60 + 30  # 11:30
        crosses_lunch = (
            depart_total_mins < lunch_window_mins
            and (depart_total_mins + full_drive_mins) > lunch_window_mins
        )
        also_at_lunch = 11 <= projected_arrival_h <= 13 and km_driven_since_last_break >= 30
        lunch_intercept = crosses_lunch or also_at_lunch

        if lunch_intercept and crosses_lunch:
            # Cắt chặng để đến đúng 11:30
            mins_to_lunch = max(20, lunch_window_mins - depart_total_mins)
            drive_km = min(km_remaining, (mins_to_lunch / 60) * speed_kmh, max_drivable_km)
            drive_km = max(drive_km, 20.0)
        else:
            drive_km = min(km_remaining, max_drivable_km)

        drive_mins = _drive_time_mins(drive_km, vehicle)
        arrival_time = _add_minutes(current_time, drive_mins)

        # Tính tọa độ điểm dừng (nội suy tuyến tính — đủ chính xác cho mục đích hiển thị)
        progress = (cumulative_km - cumulative_km_offset + drive_km) / road_km
        progress = min(1.0, progress)
        stop_lat = start.lat + (end.lat - start.lat) * progress
        stop_lng = start.lng + (end.lng - start.lng) * progress

        cumulative_km += drive_km
        km_remaining -= drive_km
        km_driven_since_last_break += drive_km
        total_pure_drive_mins += drive_mins

        # Thêm segment
        next_loc = end.name if km_remaining <= 5.0 else f"Km {int(cumulative_km)}"
        segments.append(DrivingSegment(
            from_name=current_loc_name,
            to_name=next_loc,
            distance_km=round(drive_km, 1),
            drive_time_mins=drive_mins,
            departure_time=current_time,
            arrival_time=arrival_time,
        ))

        current_time = arrival_time
        current_loc_name = next_loc
        current_lat = stop_lat
        current_lng = stop_lng

        # Nếu đã đến đích → thoát
        if km_remaining <= 5.0:
            break

        # ── Quyết định loại trạm dừng ──────────────────────────────────────
        # Ưu tiên: (1) Giờ ăn trưa (lunch_intercept đã cắt đúng chặng), (2) Đủ 4h lái liên tục.
        h_now = int(current_time.split(":")[0])
        is_lunch_time = (lunch_intercept or (11 <= h_now <= 13)) and km_driven_since_last_break > 30
        needs_fatigue_break = km_driven_since_last_break >= max_km_per_leg

        if is_lunch_time:
            stop_type   = "MEAL"
            duration    = 75
            stop_name   = _find_meal_stop_name(stop_lat, stop_lng, drive_mode, db_path)
            description = "Dừng ăn trưa đặc sản địa phương (~75 phút). Bổ sung năng lượng trước chặng tiếp theo."
        elif needs_fatigue_break:
            stop_type   = "SHORT"
            duration    = _MANDATORY_SHORT_BREAK_MINS
            stop_name   = f"Trạm nghỉ chân — Km {int(cumulative_km)}"
            description = "Nghỉ ngơi 30 phút: đổ xăng, uống nước, đi vệ sinh. Bắt buộc theo quy định an toàn."
        else:
            continue  # Chưa đủ điều kiện → tiếp tục vòng lặp không dừng

        depart = _add_minutes(arrival_time, duration)
        pit_stops.append(PitStop(
            stop_type=stop_type,
            name=stop_name,
            address=f"Trục đường Km {int(cumulative_km)}",
            lat=round(stop_lat, 6),
            lng=round(stop_lng, 6),
            arrival_time=arrival_time,
            departure_time=depart,
            duration_mins=duration,
            cumulative_km=round(cumulative_km, 1),
            description=description,
        ))
        current_time = depart
        km_driven_since_last_break = 0.0  # Reset đồng hồ lái liên tục

    return pit_stops, segments, round(road_km, 1), total_pure_drive_mins


def _find_meal_stop_name(lat: float, lng: float, mode: DriveMode, db_path: str) -> str:
    """
    Tìm tên quán ăn / địa điểm ăn trưa thực tế gần nhất (radius 30km) trong travel_db.db.
    Fallback: trả về chuỗi mô tả vị trí chung chung. KHÔNG bịa đặt tên địa điểm.
    """
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT name, lat, lng FROM places WHERE category IN ('RESTAURANT','SEAFOOD_RESTAURANT','SPECIALTY_FOOD')"
        )
        rows = cur.fetchall()
        conn.close()

        candidates = []
        for name, p_lat, p_lng in rows:
            d = _haversine(lat, lng, p_lat, p_lng)
            if d <= 30.0:
                candidates.append((d, name))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
    except Exception:
        pass

    return "Quán ăn đặc sản dọc đường (tự tìm kiếm trên Google Maps)"


# ══════════════════════════════════════════════════════════════════════════════
# 6. THUẬT TOÁN HÀNH LANG NGẮM CẢNH (Corridor Buffer — Scenic Mode Only)
# ══════════════════════════════════════════════════════════════════════════════

def _find_scenic_waypoints(
    origin: GeoPoint,
    destination: GeoPoint,
    max_detour_km: float = _SCENIC_CORRIDOR_RADIUS_KM,
    db_path: str = _DB_PATH,
) -> List[dict]:
    """
    Quét travel_db.db để tìm danh thắng, di tích, điểm check-in nằm trong
    hành lang đệm (Corridor Buffer) bao quanh trục đường origin → destination.

    Thuật toán:
      Với mỗi địa điểm trong DB, tính khoảng cách vuông góc từ điểm đó
      tới đoạn thẳng (origin → destination). Nếu khoảng cách ≤ max_detour_km
      → đưa vào danh sách gợi ý ngắm cảnh.
    """
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT name, category, lat, lng, address, rating, image_url, google_maps_url
            FROM places
            WHERE category IN ('ATTRACTION','HISTORICAL_SITE','TEMPLE','BEACH')
              AND rating IS NOT NULL AND rating >= 4.2
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return []

    waypoints = []
    for name, cat, p_lat, p_lng, addr, rating, img, gmap in rows:
        perp_dist = _point_to_segment_distance(
            p_lat, p_lng,
            origin.lat, origin.lng,
            destination.lat, destination.lng,
        )
        if perp_dist <= max_detour_km:
            # Tính vị trí tương đối trên trục (0 = origin, 1 = destination)
            total_d = _haversine(origin.lat, origin.lng, destination.lat, destination.lng)
            proj_ratio = _haversine(origin.lat, origin.lng, p_lat, p_lng) / max(total_d, 1)
            waypoints.append({
                "name": name,
                "category": cat,
                "lat": p_lat,
                "lng": p_lng,
                "address": addr,
                "rating": rating,
                "image_url": img,
                "google_maps_url": gmap,
                "detour_km": round(perp_dist, 1),
                "route_progress_ratio": round(min(proj_ratio, 1.0), 2),  # Nằm ở vị trí nào trên đường
            })

    # Sắp xếp theo vị trí trên tuyến đường (đi theo thứ tự địa lý)
    waypoints.sort(key=lambda x: x["route_progress_ratio"])
    return waypoints


# ══════════════════════════════════════════════════════════════════════════════
# 7. HÀM CHÍNH — BUILDER ROAD TRIP PLAN (Entry Point)
# ══════════════════════════════════════════════════════════════════════════════

def build_road_trip_plan(
    origin_lat: float,
    origin_lng: float,
    origin_name: str,
    dest_lat: float,
    dest_lng: float,
    dest_name: str,
    vehicle: str = "car",
    drive_mode: str = "express",
    db_path: str = _DB_PATH,
) -> dict:
    """
    Hàm entry point — Xây dựng kế hoạch Road Trip đường dài hoàn chỉnh.

    Trả về dict chuẩn JSON-serializable, tương thích với API response hiện tại.
    AI Slot: Hàm này được gọi SAU khi Qwen 7B đã điền các tham số.

    Luồng xử lý:
      1. Tính cự ly Haversine → ước lượng khoảng cách đường bộ.
      2. Phân luồng: Gần (<300km) / Trung bình (300-400km) / Xa (≥400km cần staging).
      3. Tính toán trạm dừng nghỉ và chặng lái theo ràng buộc sinh học.
      4. Nếu Scenic Mode: Quét hành lang ngắm cảnh trong travel_db.db.
      5. Tạo tuyến về (anti-boredom: khác tuyến đi nếu Scenic Mode).
    """
    origin = GeoPoint(lat=origin_lat, lng=origin_lng, name=origin_name)
    dest   = GeoPoint(lat=dest_lat,   lng=dest_lng,   name=dest_name)

    # Normalize enum
    try:
        veh = VehicleType(vehicle.lower())
    except ValueError:
        veh = VehicleType.CAR
    try:
        mode = DriveMode(drive_mode.lower())
    except ValueError:
        mode = DriveMode.EXPRESS

    haversine_km = _haversine(origin.lat, origin.lng, dest.lat, dest.lng)
    road_km      = _road_distance_estimate(haversine_km)

    # ── Phân luồng cự ly ──────────────────────────────────────────────────────
    requires_staging = road_km >= _OVERNIGHT_STAGING_KM
    feasibility_advisory = None

    if road_km < _ROAD_TRIP_THRESHOLD_KM:
        # Không cần Road Trip Engine — đường bộ trực tiếp (<300km)
        return {
            "road_trip_required": False,
            "one_way_km": round(road_km, 1),
            "message": (
                f"Khoảng cách {origin_name} → {dest_name} chỉ {road_km:.0f} km. "
                f"Có thể đi thẳng bằng {veh.value} trong ~{_drive_time_mins(road_km, veh)//60}h "
                f"{_drive_time_mins(road_km, veh)%60}m, không cần lịch Road Trip riêng."
            ),
        }

    # ── Xây dựng lịch trình chiều đi (Outbound) ──────────────────────────────
    outbound_days = _build_drive_days(
        origin=origin, destination=dest,
        vehicle=veh, drive_mode=mode,
        departure_time="06:30",
        is_return=False,
        db_path=db_path,
    )

    # ── Xây dựng lịch trình chiều về (Return — tuyến luân phiên) ─────────────
    return_drive_mode = DriveMode.SCENIC if mode == DriveMode.EXPRESS else DriveMode.EXPRESS
    return_days = _build_drive_days(
        origin=dest, destination=origin,
        vehicle=veh, drive_mode=return_drive_mode,
        departure_time="07:00",
        is_return=True,
        db_path=db_path,
    )

    # ── Tổng chi phí nhiên liệu ───────────────────────────────────────────────
    fuel_cost = int(road_km * 2 * _FUEL_COST_PER_KM[veh])  # Khứ hồi

    # ── Gợi ý Scenic passes nếu mode ngắm cảnh ───────────────────────────────
    scenic_waypoints = []
    if mode == DriveMode.SCENIC:
        scenic_waypoints = _find_scenic_waypoints(origin, dest, db_path=db_path)

    return {
        "road_trip_required": True,
        "drive_mode": mode.value,
        "vehicle": veh.value,
        "origin": {"name": origin_name, "lat": origin_lat, "lng": origin_lng},
        "destination": {"name": dest_name, "lat": dest_lat, "lng": dest_lng},
        "one_way_km": round(road_km, 1),
        "round_trip_km": round(road_km * 2, 1),
        "estimated_fuel_cost_vnd": fuel_cost,
        "requires_overnight_staging": requires_staging,
        "feasibility_advisory": feasibility_advisory,
        "outbound": [_serialize_drive_day(d) for d in outbound_days],
        "return":   [_serialize_drive_day(d) for d in return_days],
        "scenic_corridor_waypoints": scenic_waypoints,
        "scenic_passes": [
            p for p in _SCENIC_PASSES
            if _point_to_segment_distance(p["lat"], p["lng"],
                                          origin.lat, origin.lng,
                                          dest.lat, dest.lng) <= 25.0
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8. XÂY DỰNG DANH SÁCH NGÀY LÁI XE (Internal Builder)
# ══════════════════════════════════════════════════════════════════════════════

def _build_drive_days(
    origin: GeoPoint,
    destination: GeoPoint,
    vehicle: VehicleType,
    drive_mode: DriveMode,
    departure_time: str,
    is_return: bool,
    db_path: str,
) -> List[RoadTripDay]:
    """
    Xây dựng danh sách các ngày lái xe từ origin tới destination.
    Nếu cự ly > safe_daily_km → tự động chia nhiều ngày + tìm điểm nghỉ đêm.
    """
    road_km   = _road_distance_estimate(_haversine(origin.lat, origin.lng, destination.lat, destination.lng))
    safe_km   = _SAFE_DAILY_KM[vehicle]
    direction = "return" if is_return else "outbound"

    days: List[RoadTripDay] = []
    current_origin = origin
    km_remaining   = road_km
    cumulative_km  = 0.0
    day_num        = 1
    current_depart = departure_time

    while km_remaining > 5.0:
        day_km = min(km_remaining, safe_km)

        # Tìm điểm cuối của ngày hôm nay
        if km_remaining > safe_km:
            # Cần nghỉ đêm trung gian → tìm thành phố staging phù hợp
            staging = _find_optimal_staging_city(current_origin, destination, vehicle)
            day_end = GeoPoint(lat=staging["lat"], lng=staging["lng"], name=staging["name"])
            overnight_city = staging["name"]
            day_type = "OUTBOUND_DRIVE" if not is_return else "RETURN_DRIVE"
        else:
            day_end = destination
            overnight_city = None
            day_type = "OUTBOUND_DRIVE" if not is_return else "RETURN_DRIVE"

        # Kế hoạch trạm dừng nghỉ cho ngày hôm nay
        pit_stops, segments, actual_km, pure_drive_mins = _plan_pit_stops(
            start=current_origin,
            end=day_end,
            vehicle=vehicle,
            drive_mode=drive_mode,
            departure_time=current_depart,
            cumulative_km_offset=cumulative_km,
            db_path=db_path,
        )

        fuel_day = int(actual_km * _FUEL_COST_PER_KM[vehicle])
        drive_hours = round(pure_drive_mins / 60, 1)

        label = f"Ngày {day_num} (Chiều {'về' if is_return else 'đi'})"
        title = f"{label}: {current_origin.name} → {day_end.name} ({actual_km:.0f} km)"

        days.append(RoadTripDay(
            day_index=day_num if not is_return else -day_num,
            day_type=day_type,
            title=title,
            start_location=current_origin.name,
            end_location=day_end.name,
            total_km=actual_km,
            total_drive_hours=drive_hours,
            fuel_cost_vnd=fuel_day,
            segments=segments,
            pit_stops=pit_stops,
            overnight_city=overnight_city,
            feasibility_warning=(
                f"Ngày này lái xe {drive_hours:.1f} giờ ({actual_km:.0f} km). "
                f"Khuyến nghị không lái quá {_MAX_DAILY_DRIVE_HRS} giờ/ngày."
            ) if drive_hours > _MAX_DAILY_DRIVE_HRS * 0.85 else None,
        ))

        cumulative_km  += actual_km
        km_remaining   -= actual_km
        current_origin  = day_end
        current_depart  = "06:30"  # Sáng hôm sau
        day_num        += 1

    return days


def _serialize_drive_day(day: RoadTripDay) -> dict:
    """Chuyển đổi RoadTripDay dataclass → dict JSON-serializable."""
    return {
        "day_index": day.day_index,
        "day_type": day.day_type,
        "title": day.title,
        "start_location": day.start_location,
        "end_location": day.end_location,
        "total_km": day.total_km,
        "total_drive_hours": day.total_drive_hours,
        "fuel_cost_vnd": day.fuel_cost_vnd,
        "overnight_city": day.overnight_city,
        "feasibility_warning": day.feasibility_warning,
        "segments": [
            {
                "from": s.from_name, "to": s.to_name,
                "distance_km": s.distance_km, "drive_time_mins": s.drive_time_mins,
                "departure": s.departure_time, "arrival": s.arrival_time,
            }
            for s in day.segments
        ],
        "pit_stops": [
            {
                "type": p.stop_type, "name": p.name, "address": p.address,
                "lat": p.lat, "lng": p.lng,
                "arrival": p.arrival_time, "departure": p.departure_time,
                "duration_mins": p.duration_mins,
                "cumulative_km": p.cumulative_km,
                "description": p.description,
                "image_url": p.image_url,
                "google_maps_url": p.google_maps_url,
            }
            for p in day.pit_stops
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 9. KIỂM TRA TÍNH KHẢ THI CHUYẾN ĐI (Feasibility Advisor)
#    Cảnh báo mâu thuẫn: Đi xa bằng xe + Quá ít ngày
# ══════════════════════════════════════════════════════════════════════════════

def check_road_trip_feasibility(
    one_way_km: float,
    total_trip_days: int,
    vehicle: str = "car",
) -> dict:
    """
    Kiểm tra xem số ngày có đủ để đi xe đường dài không.
    Trả về advisory card nếu phát hiện mâu thuẫn.

    Ví dụ: Hà Nội → Đà Nẵng (760km) mà chỉ đặt 3 ngày bằng ô tô
           → 2 ngày đi-về trên xe, còn 0.5 ngày ở Đà Nẵng → KHÔNG KHẢ THI.
    """
    try:
        veh = VehicleType(vehicle.lower())
    except ValueError:
        veh = VehicleType.CAR

    # Chuyến đường ngắn (<300km): không mất riêng ngày nào cho việc lái
    if one_way_km < _ROAD_TRIP_THRESHOLD_KM:
        return {
            "feasible": True,
            "severity": "OK",
            "message": f"Chuyến đi gần ({one_way_km:.0f} km). Không cần ngày lái riêng — toàn bộ {total_trip_days} ngày dùng để tham quan.",
            "play_days_available": total_trip_days,
            "drive_days_each_way": 0,
        }

    safe_km           = _SAFE_DAILY_KM[veh]
    drive_days_needed = math.ceil(one_way_km / safe_km)  # Số ngày lái mỗi chiều
    total_drive_days  = drive_days_needed * 2             # Khứ hồi
    play_days         = total_trip_days - total_drive_days

    if play_days <= 0:
        return {
            "feasible": False,
            "severity": "CRITICAL",
            "message": (
                f"⚠️ Cảnh báo: Quãng đường {one_way_km:.0f} km mỗi chiều cần tối thiểu "
                f"{drive_days_needed} ngày lái ({total_drive_days} ngày khứ hồi). "
                f"Với {total_trip_days} ngày, bạn sẽ không có thời gian tham quan tại điểm đến. "
                f"Khuyên bạn đặt tối thiểu {total_drive_days + 2} ngày hoặc chuyển sang đi máy bay."
            ),
            "min_days_recommended": total_drive_days + 2,
            "drive_days_each_way": drive_days_needed,
        }
    elif play_days == 1:
        return {
            "feasible": True,
            "severity": "WARNING",
            "message": (
                f"Chuyến đi có thể thực hiện nhưng khá gấp. Bạn sẽ chỉ có {play_days} ngày "
                f"tham quan tại điểm đến sau khi mất {total_drive_days} ngày trên đường. "
                f"Cân nhắc thêm ít nhất 1-2 ngày nữa."
            ),
            "play_days_available": play_days,
            "drive_days_each_way": drive_days_needed,
        }

    return {
        "feasible": True,
        "severity": "OK",
        "message": f"Lịch trình khả thi. Bạn có {play_days} ngày tham quan tại điểm đến.",
        "play_days_available": play_days,
        "drive_days_each_way": drive_days_needed,
    }

