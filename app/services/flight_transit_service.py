"""
HỆ THỐNG ĐIỀU PHỐI HÀNH TRÌNH HÀNG KHÔNG KHÉP KÍN (DOOR-TO-DOOR FLIGHT TRANSIT PIPELINE)
Tuân thủ Chuẩn mực Kỹ thuật Top 0.1% Kỹ sư (Principal / Staff Systems Architect) & AGENTS.md

Kiến trúc 3 Chặng Tích hợp:
1. First-mile (Đường bộ): Điểm xuất phát của du khách -> Cảng hàng không xuất phát (Goong Maps / Geodesic Fallback)
2. In-flight (Đường hàng không): Cảng hàng không xuất phát -> Cảng hàng không Cửa ngõ (Bézier Arc Polyline, Leaflet Purple Dashed)
3. Last-mile (Đường bộ): Cảng hàng không Cửa ngõ -> Khách sạn / Điểm tham quan tại tỉnh đích (3 Tùy chọn: Taxi/Grab, Bus trung chuyển, Xe máy thuê)

Đặc tính Kỹ thuật Cốt lõi:
- Zero-Failure Resiliency: Phòng thủ tuyệt đối, tự động fallback Geodesic 2 điểm khi Goong API lỗi/hết quota/mất mạng.
- Deterministic Mathematical Rigor: Quét cự ly Haversine thực tế trên 22 sân bay dân dụng trong travel_db.db.
- Gateway Airport Catchment: Thuật toán quét hành lang 150 km kết hợp bảng từ điển chuẩn hóa (Canonical Gateway Overrides).
- In-Memory LRU Cache: Bộ đệm luồng an toàn (Thread-safe) giảm độ trễ truy vấn API < 1ms và bảo vệ hạn ngạch.
"""

import os
import math
import sqlite3
import json
import re
import unicodedata
import logging
import threading
from collections import OrderedDict
from typing import List, Dict, Any, Tuple, Optional
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Nạp biến môi trường
load_dotenv()

logger = logging.getLogger("flight_transit_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ==============================================================================
# HẰNG SỐ CẤU HÌNH & QUY CHUẨN THỰC ĐỊA
# ==============================================================================
EARTH_RADIUS_KM = 6371.0
GOONG_DIRECTIONS_API_URL = "https://rsapi.goong.io/Direction"
DEFAULT_TIMEOUT_SECONDS = 3.5

# Đường dẫn mặc định tới cơ sở dữ liệu thực tế
def resolve_db_path(db_path: str = "travel_db.db") -> str:
    """Xác định đường dẫn tuyệt đối chuẩn xác tới file SQLite travel_db.db"""
    if os.path.isabs(db_path) and os.path.exists(db_path):
        return db_path
    if os.path.exists(db_path):
        return os.path.abspath(db_path)
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidate = os.path.join(project_root, "travel_db.db")
    if os.path.exists(candidate):
        return candidate
    candidate_app = os.path.join(project_root, db_path)
    if os.path.exists(candidate_app):
        return candidate_app
    return db_path

# Bảng từ điển Cửa ngõ Hàng không Chuẩn hóa (Canonical Gateway Overrides)
# Giải quyết bài toán thực tế: Các tỉnh/thành phố du lịch trọng điểm không có sân bay riêng
# hoặc sân bay địa phương hạn chế chuyến, được kết nối với trung tâm hàng không vệ tinh.
CANONICAL_GATEWAY_OVERRIDES = {
    # Quảng Nam / Hội An / Tam Kỳ -> Cửa ngõ quốc tế Đà Nẵng (DAD) (cách 24-28 km)
    "quang nam": "DAD",
    "hoi an": "DAD",
    "tam ky": "DAD",
    
    # Lào Cai / Sa Pa -> Cửa ngõ quốc tế Nội Bài (HAN) (kết nối Cao tốc Nội Bài - Lào Cai CT05)
    "lao cai": "HAN",
    "sa pa": "HAN",
    "sapa": "HAN",
    
    # Bình Thuận / Mũi Né / Phan Thiết -> Cửa ngõ quốc tế Cam Ranh (CXR) (kết nối Cao tốc Cam Lâm - Vĩnh Hảo)
    "binh thuan": "CXR",
    "mui ne": "CXR",
    "phan thiet": "CXR",
    
    # Ninh Bình -> Cửa ngõ Nội Bài (HAN) (khoảng cách 115 km qua Cao tốc Pháp Vân - Cầu Giẽ)
    "ninh binh": "HAN",
    
    # Bà Rịa - Vũng Tàu / Vũng Tàu -> Cửa ngõ Tân Sơn Nhất (SGN) (hoặc Long Thành tương lai)
    "ba ria vung tau": "SGN",
    "vung tau": "SGN",
    
    # Các tỉnh Đông Bắc / Tây Bắc vệ tinh của Nội Bài (HAN)
    "ha giang": "HAN",
    "cao bang": "HAN",
    "yen bai": "HAN",
    "tuyen quang": "HAN",
    "bac kan": "HAN",
    "lang son": "HAN",
}


# ==============================================================================
# HÀM BỔ TRỢ CHUẨN HÓA VĂN BẢN & TOÁN HỌC HAVERSINE
# ==============================================================================
def normalize_text(text: str) -> str:
    """
    Chuẩn hóa chuỗi tiếng Việt: Bỏ dấu thanh, chuyển chữ thường, loại bỏ ký tự lạ.
    Ví dụ: 'Quảng Nam' -> 'quang nam', 'Sa Pa' -> 'sa pa'
    """
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)
    text = text.replace('đ', 'd').replace('Đ', 'D')
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return ' '.join(text.split())

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Tính khoảng cách mặt cầu lớn giữa 2 tọa độ GPS (km) theo công thức Haversine thuần túy.
    Độ chính xác xác định (Deterministic Engine), bán kính Trái Đất R = 6371.0 km.
    """
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(EARTH_RADIUS_KM * c, 2)

def format_duration(minutes: int) -> str:
    """Định dạng thời gian thân thiện tiếng Việt"""
    if minutes < 60:
        return f"{minutes} phút"
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"{hours} giờ"
    return f"{hours} giờ {rem} phút"


# ==============================================================================
# 1. DATA CONTRACTS & SCHEMAS PYDANTIC (TYPE HINTS CHUẨN MỰC)
# ==============================================================================
class AirportModel(BaseModel):
    """Mô hình dữ liệu cảng hàng không dân dụng từ travel_db.db"""
    id: Optional[int] = None
    iata_code: str = Field(..., description="Mã IATA 3 ký tự (HAN, SGN, DAD, CXR...)")
    name: str = Field(..., description="Tên cảng hàng không")
    province_name: Optional[str] = Field("", description="Tỉnh / Thành phố trực thuộc")
    city_served: Optional[str] = Field("", description="Đô thị / Khu vực phục vụ chính")
    is_international: bool = Field(False, description="Sân bay Quốc tế / Hub lớn")
    lat: float = Field(..., description="Vĩ độ GPS")
    lng: float = Field(..., description="Kinh độ GPS")
    address: Optional[str] = Field("", description="Địa chỉ thực tế")
    rating: Optional[float] = None
    review_count: Optional[int] = None
    google_place_id: Optional[str] = None
    google_maps_url: Optional[str] = None
    image_url: Optional[str] = None
    phone_number: Optional[str] = None
    website: Optional[str] = None

class GroundTransitLeg(BaseModel):
    """Mô hình chặng trung chuyển đường bộ (First-mile hoặc Last-mile)"""
    mode: str = Field("car", description="Phương tiện di chuyển: car, taxi, bus, rental_motorbike")
    leg_type: Optional[str] = Field(None, description="first_mile hoặc last_mile")
    from_name: str = Field(..., description="Tên điểm đón")
    from_coords: Tuple[float, float] = Field(..., description="(Vĩ độ, Kinh độ) điểm đón")
    to_name: str = Field(..., description="Tên điểm đến")
    to_coords: Tuple[float, float] = Field(..., description="(Vĩ độ, Kinh độ) điểm đến")
    distance_km: float = Field(..., description="Quãng đường thực tế (km)")
    duration_minutes: int = Field(..., description="Thời gian di chuyển ước tính (phút)")
    duration_text: str = Field(..., description="Chuỗi văn bản thời gian ('45 phút', '1 giờ 15 phút')")
    estimated_cost_vnd: int = Field(..., description="Chi phí đường bộ ước tính (VNĐ)")
    polyline: List[List[float]] = Field(..., description="Đa tuyến tọa độ [[lat, lng], ...] cho Leaflet")
    options: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Các tùy chọn phương tiện thay thế")
    transport_suggestions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    is_fallback: bool = Field(False, description="Đánh dấu dữ liệu fallback Geodesic khi Goong API ngoại tuyến")

class FlightLeg(BaseModel):
    """Mô hình chặng bay trên không giữa 2 sân bay"""
    origin_airport: AirportModel = Field(..., description="Sân bay xuất phát")
    dest_airport: AirportModel = Field(..., description="Sân bay cửa ngõ đích")
    gateway_airport: Optional[AirportModel] = Field(None, description="Bí danh sân bay cửa ngõ đích")
    flight_distance_km: float = Field(..., description="Khoảng cách đường bay (km)")
    flight_duration_minutes: int = Field(..., description="Thời gian bay thực tế (phút)")
    flight_duration_text: str = Field(..., description="Chuỗi thời gian bay ('1 giờ 20 phút')")
    recommended_airlines: List[str] = Field(..., description="Danh sách hãng bay khuyến nghị")
    suggested_airlines: Optional[List[str]] = Field(None, description="Bí danh hãng bay khuyến nghị")
    estimated_flight_cost_vnd: int = Field(..., description="Chi phí vé máy bay ước tính cho đoàn (VNĐ)")
    estimated_ticket_price_range: Optional[str] = Field(None, description="Khung giá vé tham khảo/người")
    flight_arc_polyline: List[List[float]] = Field(..., description="Tọa độ đường cong Bézier nét đứt cho Leaflet")
    arc_coordinates: Optional[List[List[float]]] = Field(None, description="Bí danh tọa độ đường cong Bézier")

class TransitTimelineCard(BaseModel):
    """Thẻ sự kiện mốc thời gian sinh học du lịch trên Timeline"""
    time: str = Field(..., description="Khung giờ đề xuất ('06:00', '08:30')")
    icon: str = Field(..., description="Biểu tượng emoji đại diện ('🚕', '🛂', '✈️', '🧳', '🏨', '🏡')")
    title: str = Field(..., description="Tiêu đề hoạt động")
    description: str = Field(..., description="Mô tả hướng dẫn chi tiết")
    badge_label: str = Field(..., description="Nhãn phân loại chặng")
    duration_mins: int = Field(..., description="Thời lượng hoạt động (phút)")

class FlightTransitJourney(BaseModel):
    """Hành trình hàng không một chiều hoàn chỉnh kèm thẻ Timeline"""
    direction: str = Field(..., description="'outbound' (lượt đi) hoặc 'return' (lượt về)")
    first_mile: GroundTransitLeg
    flight_leg: FlightLeg
    last_mile: GroundTransitLeg
    timeline_cards: List[TransitTimelineCard]
    total_transit_duration_mins: int

class DoorToDoorFlightPipeline(BaseModel):
    """Cấu trúc dữ liệu toàn diện của Đường ống Hàng không Khép kín 2 chiều"""
    is_flight_required: bool = Field(True, description="Chuyến đi có thỏa mãn điều kiện cần bay (cự ly >= 300km hoặc chủ động chọn bay)")
    is_flight_applicable: bool = Field(True, description="Bí danh tính tương thích của chặng bay")
    interprovincial_distance_km: float = Field(..., description="Khoảng cách liên tỉnh thẳng giữa xuất phát và điểm đến (km)")
    origin_airport: Optional[AirportModel] = None
    destination_gateway_airport: Optional[AirportModel] = None
    gateway_airport: Optional[AirportModel] = None
    outbound_first_mile: Optional[GroundTransitLeg] = None
    outbound_flight: Optional[FlightLeg] = None
    outbound_last_mile: Optional[GroundTransitLeg] = None
    return_first_mile: Optional[GroundTransitLeg] = None
    return_flight: Optional[FlightLeg] = None
    return_last_mile: Optional[GroundTransitLeg] = None
    total_transit_cost_vnd: int = Field(0, description="Tổng chi phí trung chuyển hàng không & đường bộ toàn chuyến (VNĐ)")
    map_layers: Optional[Dict[str, Any]] = Field(None, description="Các lớp dữ liệu hình học đóng gói sẵn cho Leaflet.js")
    outbound_timeline_cards: Optional[List[TransitTimelineCard]] = None
    return_timeline_cards: Optional[List[TransitTimelineCard]] = None
    outbound: Optional[FlightTransitJourney] = None
    return_journey: Optional[FlightTransitJourney] = None


# ==============================================================================
# 2. BỘ GIẢI MÃ POLYLINE GOOGLE / GOONG MAPS (THUẦN PYTHON, ZERO-DEPENDENCY)
# ==============================================================================
def decode_polyline(encoded_str: str) -> List[List[float]]:
    """
    Giải mã chuỗi đa tuyến Polyline mã hóa chuẩn Google / Goong Maps thành mảng tọa độ [[lat, lng], ...].
    Thuật toán chuẩn xác thực thi thuần Python theo triết lý Ponytail Lazy Dev (không cần cài thêm thư viện ngoài).
    """
    if not encoded_str:
        return []
    
    coordinates: List[List[float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded_str)

    while index < length:
        # Giải mã vĩ độ (Latitude)
        shift = 0
        result = 0
        while True:
            if index >= length:
                break
            byte = ord(encoded_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Giải mã kinh độ (Longitude)
        shift = 0
        result = 0
        while True:
            if index >= length:
                break
            byte = ord(encoded_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append([round(lat / 1e5, 6), round(lng / 1e5, 6)])

    return coordinates


# ==============================================================================
# 3. THREAD-SAFE IN-MEMORY LRU CACHE CHO GOONG DIRECTIONS API
# ==============================================================================
class LRUCache:
    """Bộ nhớ đệm LRU Thread-Safe trong RAM, tối ưu hóa thời gian phản hồi và bảo vệ hạn ngạch API"""
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self.capacity:
                self._cache.popitem(last=False)

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

# Khởi tạo singleton cache toàn cục
_DIRECTIONS_CACHE = LRUCache(capacity=1000)


# ==============================================================================
# 4. TRUY VẤN VÀ KHẢO SÁT SÂN BAY TỪ TRAVEL_DB.DB
# ==============================================================================
def get_all_airports(db_path: str = "travel_db.db") -> List[AirportModel]:
    """
    Truy vấn toàn bộ 22 cảng hàng không dân dụng Việt Nam từ travel_db.db.
    Được thẩm tra 100% dữ liệu thực địa từ Google Maps Scraper.
    """
    real_db_path = resolve_db_path(db_path)
    if not os.path.exists(real_db_path):
        raise FileNotFoundError(f"Không tìm thấy cơ sở dữ liệu travel_db.db tại đường dẫn: {real_db_path}")

    conn = sqlite3.connect(real_db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT id, iata_code, name, province_name, city_served, is_international,
               lat, lng, address, rating, review_count, google_place_id, google_maps_url,
               image_url, phone_number, website
        FROM airports
        ORDER BY id ASC
    """)
    rows = c.fetchall()
    conn.close()

    airports: List[AirportModel] = []
    for r in rows:
        airports.append(AirportModel(
            id=r["id"],
            iata_code=r["iata_code"],
            name=r["name"],
            province_name=r["province_name"] or "",
            city_served=r["city_served"] or "",
            is_international=bool(r["is_international"]),
            lat=float(r["lat"]),
            lng=float(r["lng"]),
            address=r["address"] or "",
            rating=r["rating"],
            review_count=r["review_count"],
            google_place_id=r["google_place_id"],
            google_maps_url=r["google_maps_url"],
            image_url=r["image_url"],
            phone_number=r["phone_number"],
            website=r["website"]
        ))
    return airports

def find_nearest_airport(
    origin_lat: float,
    origin_lng: float,
    db_path: str = "travel_db.db"
) -> AirportModel:
    """
    Phát hiện Sân bay Xuất phát gần nhất từ tọa độ của người dùng.
    Sử dụng khoảng cách Haversine tính toán trên toàn bộ 22 sân bay trong travel_db.db.
    """
    airports = get_all_airports(db_path)
    if not airports:
        raise ValueError("Cơ sở dữ liệu travel_db.db không có bản ghi sân bay nào!")

    nearest = min(
        airports,
        key=lambda a: haversine_distance(origin_lat, origin_lng, a.lat, a.lng)
    )
    return nearest

def find_gateway_airport(
    dest_province: str,
    dest_lat: float,
    dest_lng: float,
    db_path: str = "travel_db.db",
    max_radius_km: float = 150.0
) -> AirportModel:
    """
    Phát hiện Sân bay Cửa ngõ (Gateway Airport) cho tỉnh/thành phố đích:
    1. Kiểm tra bảng chuẩn hóa (Canonical Gateway Overrides):
       - Hội An / Quảng Nam -> DAD (Đà Nẵng)
       - Sa Pa / Lào Cai -> HAN (Nội Bài)
       - Mũi Né / Bình Thuận -> CXR (Cam Ranh)
       - Ninh Bình -> HAN (Nội Bài)
       - Vũng Tàu -> SGN (Tân Sơn Nhất)
    2. Nếu không nằm trong ngoại lệ: Lọc các sân bay trong hành lang bán kính max_radius_km (150 km).
       Chấm điểm ưu tiên sân bay quốc tế/hub lớn và khoảng cách gần nhất:
       Score = (2.0 if is_international else 1.0) * 100.0 - distance_km
    3. Nếu không có sân bay nào trong bán kính 150 km: Chọn sân bay gần nhất toàn quốc.
    """
    airports = get_all_airports(db_path)
    if not airports:
        raise ValueError("Cơ sở dữ liệu travel_db.db không có bản ghi sân bay nào!")

    # 1. Kiểm tra Canonical Gateway Overrides
    norm_dest = normalize_text(dest_province)
    if norm_dest and len(norm_dest) >= 3:
        for pattern, target_iata in CANONICAL_GATEWAY_OVERRIDES.items():
            if pattern in norm_dest or norm_dest == pattern:
                matched = next((a for a in airports if a.iata_code == target_iata), None)
                if matched:
                    return matched

    # 2. Quét bán kính hành lang max_radius_km
    airports_within_radius: List[Tuple[float, AirportModel]] = []
    for a in airports:
        d = haversine_distance(dest_lat, dest_lng, a.lat, a.lng)
        if d <= max_radius_km:
            airports_within_radius.append((d, a))

    if airports_within_radius:
        # Chấm điểm Hub trọng số
        best_airport = max(
            airports_within_radius,
            key=lambda item: (2.0 if item[1].is_international else 1.0) * 100.0 - item[0]
        )[1]
        return best_airport

    # 3. Fallback: Chọn sân bay gần nhất
    return min(airports, key=lambda a: haversine_distance(dest_lat, dest_lng, a.lat, a.lng))


# ==============================================================================
# 5. ĐỊNH TUYẾN ĐƯỜNG BỘ & ZERO-FAILURE RESILIENCY (GOONG MAPS + GEODESIC)
# ==============================================================================
def generate_ground_options(distance_km: float, duration_minutes: int, duration_text: str) -> List[Dict[str, Any]]:
    """
    Khởi tạo 3 phương án di chuyển mặt đất thực tế tại cửa ngõ sân bay:
    1. Taxi / Xe công nghệ (Grab / Xanh SM)
    2. Xe buýt sân bay / Shuttle Bus trung chuyển
    3. Thuê xe máy giao tận bãi đỗ sân bay
    """
    taxi_cost = max(60000, int(distance_km * 13500 + 25000))
    bus_cost = 40000
    bus_duration_mins = duration_minutes + 15
    rental_cost = 130000

    return [
        {
            "mode": "taxi",
            "name": "Taxi / Xe công nghệ (Grab, Xanh SM)",
            "estimated_cost_vnd": taxi_cost,
            "cost_display": f"{taxi_cost:,} đ",
            "duration_minutes": duration_minutes,
            "duration_text": duration_text,
            "description": "Đưa đón tận sảnh, thoải mái khi mang nhiều hành lý hoặc đi theo gia đình/nhóm.",
            "badge": "Khuyên dùng cho gia đình"
        },
        {
            "mode": "bus",
            "name": "Xe buýt sân bay / Shuttle Bus trung chuyển",
            "estimated_cost_vnd": bus_cost,
            "cost_display": f"{bus_cost:,} đ / người",
            "duration_minutes": bus_duration_mins,
            "duration_text": format_duration(bus_duration_mins),
            "description": "Tuyến xe buýt sân bay cố định về trung tâm đô thị, tiết kiệm chi phí tối đa cho khách đi lẻ.",
            "badge": "Tiết kiệm chi phí"
        },
        {
            "mode": "rental_motorbike",
            "name": "Thuê xe máy nhận trực tiếp tại sân bay",
            "estimated_cost_vnd": rental_cost,
            "cost_display": f"{rental_cost:,} đ / ngày",
            "duration_minutes": duration_minutes,
            "duration_text": duration_text,
            "description": "Nhận xe máy ngay tại bãi xe sân bay, linh hoạt tự do khám phá theo phong cách du lịch trải nghiệm.",
            "badge": "Tự do & Linh hoạt"
        }
    ]

def get_ground_directions(
    origin_coords: Tuple[float, float],
    dest_coords: Tuple[float, float],
    vehicle: str = "car",
    origin_name: str = "Điểm xuất phát",
    dest_name: str = "Điểm đến",
    leg_type: str = "first_mile",
    api_key: Optional[str] = None
) -> GroundTransitLeg:
    """
    Định tuyến đường bộ trung chuyển qua Goong Directions API kết hợp LRU Cache và Fallback phòng thủ:
    - Nếu API hoạt động: Trả về quãng đường, thời gian và đa tuyến uốn lượn chính xác.
    - Nếu API thiếu key, lỗi 403, hết quota hoặc rớt mạng: Tự động fallback về đường thẳng Geodesic 2 điểm,
      ước tính thời gian ở vận tốc 40 km/h và tính chi phí hợp lý. TUYỆT ĐỐI KHÔNG NÉM LỖI 500.
    """
    origin_lat, origin_lng = origin_coords
    dest_lat, dest_lng = dest_coords

    # Ánh xạ vehicle sang chuẩn Goong
    v_map = {
        "car": "car",
        "taxi": "taxi",
        "motorbike": "bike",
        "bike": "bike",
        "van": "car",
        "bus": "car"
    }
    goong_vehicle = v_map.get(vehicle.lower(), "car")

    # Kiểm tra LRU Cache
    cache_key = f"{round(origin_lat, 5)},{round(origin_lng, 5)}_{round(dest_lat, 5)},{round(dest_lng, 5)}_{goong_vehicle}"
    cached_leg = _DIRECTIONS_CACHE.get(cache_key)
    if cached_leg is not None:
        # Cập nhật lại tên điểm và trả về bản sao
        leg_dict = cached_leg.model_dump()
        leg_dict["from_name"] = origin_name
        leg_dict["to_name"] = dest_name
        leg_dict["leg_type"] = leg_type
        return GroundTransitLeg(**leg_dict)

    # Thử gọi Goong Directions API
    effective_key = api_key or os.getenv("GOONG_API_KEY")
    goong_success = False
    polyline: List[List[float]] = []
    distance_km: float = 0.0
    duration_minutes: int = 0
    duration_text: str = ""

    if effective_key:
        try:
            req_url = (
                f"{GOONG_DIRECTIONS_API_URL}?"
                f"origin={origin_lat},{origin_lng}&"
                f"destination={dest_lat},{dest_lng}&"
                f"vehicle={goong_vehicle}&"
                f"api_key={effective_key}"
            )
            resp = requests.get(req_url, timeout=DEFAULT_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                data = resp.json()
                routes = data.get("routes", [])
                if routes:
                    route = routes[0]
                    points_str = route.get("overview_polyline", {}).get("points", "")
                    decoded = decode_polyline(points_str)
                    if decoded:
                        polyline = decoded
                        legs = route.get("legs", [])
                        if legs:
                            leg_data = legs[0]
                            dist_val = leg_data.get("distance", {}).get("value", 0)  # mét
                            dur_val = leg_data.get("duration", {}).get("value", 0)   # giây
                            distance_km = round(dist_val / 1000.0, 2)
                            duration_minutes = max(1, int(round(dur_val / 60.0)))
                            duration_text = leg_data.get("duration", {}).get("text") or format_duration(duration_minutes)
                            goong_success = True
        except Exception as e:
            logger.warning(f"Goong Directions API không phản hồi hoặc lỗi ({e}). Tự động kích hoạt Geodesic Fallback.")

    # Cơ chế phòng thủ Fallback Geodesic
    if not goong_success:
        haversine_dist = haversine_distance(origin_lat, origin_lng, dest_lat, dest_lng)
        # Hệ số uốn lượn đường bộ Việt Nam ~1.25x
        distance_km = max(0.5, round(haversine_dist * 1.25, 2))
        # Vận tốc trung bình trong đô thị và liên tỉnh Việt Nam ~40 km/h
        duration_minutes = max(5, int(round((distance_km / 40.0) * 60)))
        duration_text = format_duration(duration_minutes)
        polyline = [
            [round(origin_lat, 6), round(origin_lng, 6)],
            [round(dest_lat, 6), round(dest_lng, 6)]
        ]

    # Tính chi phí đường bộ ước tính
    if vehicle.lower() in ["motorbike", "bike"]:
        estimated_cost = max(20000, 10000 + int(distance_km * 4000))
    elif vehicle.lower() == "taxi":
        estimated_cost = max(50000, 20000 + int(distance_km * 13500))
    else:  # car / van
        estimated_cost = max(40000, 15000 + int(distance_km * 12500))

    options = generate_ground_options(distance_km, duration_minutes, duration_text)

    leg = GroundTransitLeg(
        mode=vehicle,
        leg_type=leg_type,
        from_name=origin_name,
        from_coords=(origin_lat, origin_lng),
        to_name=dest_name,
        to_coords=(dest_lat, dest_lng),
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        duration_text=duration_text,
        estimated_cost_vnd=estimated_cost,
        polyline=polyline,
        options=options,
        transport_suggestions=options,
        is_fallback=(not goong_success)
    )

    # Lưu kết quả vào LRU Cache
    _DIRECTIONS_CACHE.set(cache_key, leg)
    return leg


# ==============================================================================
# 6. MÔ PHỎNG ĐƯỜNG CONG HÀNG KHÔNG BÉZIER CHO BẢN ĐỒ LEAFLET
# ==============================================================================
def generate_flight_arc(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    num_points: int = 20
) -> List[List[float]]:
    """
    Tạo mảng tọa độ đường cong Bézier bậc 2 (Quadratic Bézier Curve) thể hiện đường bay trên không.
    Được tối ưu hóa cho hiển thị bản đồ Leaflet.js (nét đứt màu tím #8B5CF6, dashArray '8, 8').
    Độ cong uốn lượn nhẹ về phía biển Đông theo dải đất hình chữ S của Việt Nam.
    """
    num_points = max(2, num_points)
    mid_lat = (origin_lat + dest_lat) / 2.0
    mid_lng = (origin_lng + dest_lng) / 2.0

    dlat = dest_lat - origin_lat
    dlng = dest_lng - origin_lng
    chord_len = math.sqrt(dlat**2 + dlng**2)

    if chord_len < 1e-6:
        return [[round(origin_lat, 6), round(origin_lng, 6)], [round(dest_lat, 6), round(dest_lng, 6)]]

    # Vector pháp tuyến vuông góc với dây cung
    norm_lat = -dlng / chord_len
    norm_lng = dlat / chord_len

    # Đảm bảo độ cong hướng ra phía Đông (kinh độ tăng) cho lộ trình Bắc - Nam
    curvature = 0.15 * chord_len
    if norm_lng < 0:
        norm_lat = -norm_lat
        norm_lng = -norm_lng

    ctrl_lat = mid_lat + norm_lat * curvature
    ctrl_lng = mid_lng + norm_lng * curvature

    arc_points: List[List[float]] = []
    for i in range(num_points):
        t = i / (num_points - 1)
        # Công thức Bézier bậc 2: B(t) = (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
        b_lat = (1 - t)**2 * origin_lat + 2 * (1 - t) * t * ctrl_lat + (t**2) * dest_lat
        b_lng = (1 - t)**2 * origin_lng + 2 * (1 - t) * t * ctrl_lng + (t**2) * dest_lng
        arc_points.append([round(b_lat, 6), round(b_lng, 6)])

    return arc_points


# ==============================================================================
# 7. KHỞI TẠO THẺ TIMELINE THEO NHỊP SINH HỌC HÀNG KHÔNG VIỆT NAM
# ==============================================================================
def generate_biological_timeline_cards(
    origin_airport: AirportModel,
    dest_airport: AirportModel,
    first_mile: GroundTransitLeg,
    flight: FlightLeg,
    last_mile: GroundTransitLeg,
    origin_name: str,
    dest_name: str
) -> Tuple[List[TransitTimelineCard], List[TransitTimelineCard]]:
    """
    Tạo các thẻ Timeline sinh học chuẩn xác cho Ngày 1 (Lượt đi) và Ngày cuối (Lượt về):
    - Đệm check-in an ninh 90-105 phút trước bay.
    - Nhận hành lý băng chuyền 30 phút sau hạ cánh.
    - Gợi ý trung chuyển mặt đất (Taxi/Bus/Thuê xe máy).
    """
    airlines_str = ", ".join(flight.recommended_airlines)

    # --- Ngày 1: Lượt đi ---
    outbound_cards = [
        TransitTimelineCard(
            time="06:00",
            icon="🚕",
            title=f"Di chuyển ra sân bay {origin_airport.name}",
            description=f"Xe đón từ {origin_name} ra cảng hàng không ({first_mile.distance_km} km, ~{first_mile.duration_text}).",
            badge_label="First-mile (Đường bộ)",
            duration_mins=first_mile.duration_minutes
        ),
        TransitTimelineCard(
            time="06:50",
            icon="🛂",
            title=f"Làm thủ tục & Kiểm tra an ninh tại {origin_airport.iata_code}",
            description=f"Có mặt trước giờ bay 90 - 105 phút tại {origin_airport.name} để gửi hành lý ký gửi, xuất trình CCCD/Hộ chiếu và qua cửa soi chiếu an ninh.",
            badge_label="Check-in & An ninh",
            duration_mins=105
        ),
        TransitTimelineCard(
            time="08:35",
            icon="✈️",
            title=f"Chuyến bay {origin_airport.iata_code} ➔ {dest_airport.iata_code}",
            description=f"Bay thẳng từ {origin_airport.name} đến {dest_airport.name}. Thời gian bay: {flight.flight_duration_text}. Hãng bay khuyến nghị: {airlines_str}.",
            badge_label="Chặng bay trên không",
            duration_mins=flight.flight_duration_minutes
        ),
        TransitTimelineCard(
            time="09:55",
            icon="🧳",
            title=f"Hạ cánh & Nhận hành lý tại {dest_airport.name}",
            description=f"Hạ cánh tại ga đến {dest_airport.iata_code}, nhận hành lý ký gửi tại băng chuyền và ổn định tư trang chuẩn bị đón xe.",
            badge_label="Ga đến",
            duration_mins=30
        ),
        TransitTimelineCard(
            time="10:25",
            icon="🏨",
            title=f"Di chuyển từ sân bay về {dest_name}",
            description=f"Chặng đường bộ {last_mile.distance_km} km (~{last_mile.duration_text}). Tùy chọn: Taxi/Grab đón sảnh, Xe buýt sân bay, hoặc Nhận xe máy thuê trực tiếp.",
            badge_label="Last-mile (Về điểm đến)",
            duration_mins=last_mile.duration_minutes
        )
    ]

    # --- Ngày cuối: Lượt về ---
    return_cards = [
        TransitTimelineCard(
            time="13:30",
            icon="🚕",
            title=f"Trả phòng & Di chuyển ra sân bay {dest_airport.name}",
            description=f"Rời điểm lưu trú {dest_name}, di chuyển {last_mile.distance_km} km ra cảng hàng không cửa ngõ {dest_airport.iata_code}.",
            badge_label="Ra sân bay",
            duration_mins=last_mile.duration_minutes
        ),
        TransitTimelineCard(
            time="14:20",
            icon="🛂",
            title=f"Check-in chiều về tại {dest_airport.iata_code}",
            description=f"Làm thủ tục chuyến bay chiều về, ký gửi hành lý đặc sản và qua cửa kiểm tra an ninh tại {dest_airport.name}.",
            badge_label="Thủ tục chiều về",
            duration_mins=105
        ),
        TransitTimelineCard(
            time="16:05",
            icon="✈️",
            title=f"Chuyến bay về {dest_airport.iata_code} ➔ {origin_airport.iata_code}",
            description=f"Bay thẳng về {origin_airport.name}. Thời gian bay: {flight.flight_duration_text}.",
            badge_label="Bay chiều về",
            duration_mins=flight.flight_duration_minutes
        ),
        TransitTimelineCard(
            time="17:25",
            icon="🏡",
            title=f"Hạ cánh tại {origin_airport.iata_code} & Về lại {origin_name}",
            description=f"Hạ cánh tại {origin_airport.name}, nhận hành lý và đón xe về nhà ({first_mile.distance_km} km), kết thúc trọn vẹn kỳ nghỉ.",
            badge_label="Về nhà an toàn",
            duration_mins=first_mile.duration_minutes + 30
        )
    ]

    return outbound_cards, return_cards


# ==============================================================================
# 8. XÂY DỰNG ĐƯỜNG ỐNG HÀNG KHÔNG KHÉP KÍN (BUILD FLIGHT PIPELINE)
# ==============================================================================
def build_flight_transit_pipeline(
    origin_coords: Tuple[float, float],
    dest_coords: Tuple[float, float],
    dest_province: str = "",
    origin_name: str = "Vị trí xuất phát",
    dest_name: str = "Điểm đến",
    group_size: int = 2,
    prefer_flight: bool = False,
    vehicle_type: str = "car",
    db_path: str = "travel_db.db"
) -> Optional[DoorToDoorFlightPipeline]:
    """
    Xây dựng toàn bộ mô hình đường ống trung chuyển 3 chặng khép kín:
    - Kiểm tra điều kiện cự ly liên tỉnh D >= 300 km hoặc yêu cầu prefer_flight.
    - Tìm sân bay xuất phát & sân bay cửa ngõ đích.
    - Tạo các chặng đường bộ Goong/Geodesic và chặng bay Bézier.
    - Đóng gói dữ liệu bản đồ Leaflet.js.
    """
    origin_lat, origin_lng = origin_coords
    dest_lat, dest_lng = dest_coords
    interprovincial_dist = haversine_distance(origin_lat, origin_lng, dest_lat, dest_lng)

    # Nếu cự ly < 300 km và người dùng không yêu cầu đi máy bay: Giữ nguyên đường bộ
    if interprovincial_dist < 300.0 and not prefer_flight:
        return DoorToDoorFlightPipeline(
            is_flight_required=False,
            is_flight_applicable=False,
            interprovincial_distance_km=interprovincial_dist,
            total_transit_cost_vnd=0
        )

    # 1. Phát hiện Cảng hàng không xuất phát và Cửa ngõ đích
    origin_airport = find_nearest_airport(origin_lat, origin_lng, db_path=db_path)
    gateway_airport = find_gateway_airport(dest_province, dest_lat, dest_lng, db_path=db_path)

    # Nếu cùng một sân bay phục vụ cả 2 điểm (ví dụ di chuyển trong cùng tỉnh/thành)
    if origin_airport.iata_code == gateway_airport.iata_code:
        return DoorToDoorFlightPipeline(
            is_flight_required=False,
            is_flight_applicable=False,
            interprovincial_distance_km=interprovincial_dist,
            origin_airport=origin_airport,
            destination_gateway_airport=gateway_airport,
            gateway_airport=gateway_airport,
            total_transit_cost_vnd=0
        )

    # 2. Xây dựng Chặng 1: First-mile (Đường bộ ra sân bay xuất phát)
    outbound_first_mile = get_ground_directions(
        origin_coords=(origin_lat, origin_lng),
        dest_coords=(origin_airport.lat, origin_airport.lng),
        vehicle=vehicle_type,
        origin_name=origin_name,
        dest_name=origin_airport.name,
        leg_type="first_mile"
    )

    # 3. Xây dựng Chặng 2: In-flight (Chặng bay trên không)
    flight_dist = haversine_distance(origin_airport.lat, origin_airport.lng, gateway_airport.lat, gateway_airport.lng)
    # Vận tốc hành trình ~750 km/h + 30 phút leo/hạ cao độ
    flight_dur_mins = max(45, int(round(30 + (flight_dist / 750.0) * 60)))
    flight_dur_text = format_duration(flight_dur_mins)
    recommended_airlines = ["Vietnam Airlines", "Vietjet Air", "Bamboo Airways"]

    # Ước tính giá vé máy bay khứ hồi tham khảo theo dải cự ly
    ticket_price_one_way = 1200000 if flight_dist < 700 else 1650000
    ticket_price_range = "950.000 đ - 1.450.000 đ / vé" if flight_dist < 700 else "1.350.000 đ - 2.200.000 đ / vé"
    total_flight_cost_outbound = ticket_price_one_way * max(1, group_size)

    flight_arc_outbound = generate_flight_arc(
        origin_airport.lat, origin_airport.lng,
        gateway_airport.lat, gateway_airport.lng,
        num_points=25
    )

    outbound_flight = FlightLeg(
        origin_airport=origin_airport,
        dest_airport=gateway_airport,
        gateway_airport=gateway_airport,
        flight_distance_km=flight_dist,
        flight_duration_minutes=flight_dur_mins,
        flight_duration_text=flight_dur_text,
        recommended_airlines=recommended_airlines,
        suggested_airlines=recommended_airlines,
        estimated_flight_cost_vnd=total_flight_cost_outbound,
        estimated_ticket_price_range=ticket_price_range,
        flight_arc_polyline=flight_arc_outbound,
        arc_coordinates=flight_arc_outbound
    )

    # 4. Xây dựng Chặng 3: Last-mile (Đường bộ từ sân bay cửa ngõ về khách sạn/điểm đến)
    outbound_last_mile = get_ground_directions(
        origin_coords=(gateway_airport.lat, gateway_airport.lng),
        dest_coords=(dest_lat, dest_lng),
        vehicle=vehicle_type,
        origin_name=gateway_airport.name,
        dest_name=dest_name,
        leg_type="last_mile"
    )

    # 5. Xây dựng Chiều về (Return Journey)
    return_first_mile = get_ground_directions(
        origin_coords=(dest_lat, dest_lng),
        dest_coords=(gateway_airport.lat, gateway_airport.lng),
        vehicle=vehicle_type,
        origin_name=dest_name,
        dest_name=gateway_airport.name,
        leg_type="first_mile"
    )

    flight_arc_return = generate_flight_arc(
        gateway_airport.lat, gateway_airport.lng,
        origin_airport.lat, origin_airport.lng,
        num_points=25
    )

    return_flight = FlightLeg(
        origin_airport=gateway_airport,
        dest_airport=origin_airport,
        gateway_airport=origin_airport,
        flight_distance_km=flight_dist,
        flight_duration_minutes=flight_dur_mins,
        flight_duration_text=flight_dur_text,
        recommended_airlines=recommended_airlines,
        suggested_airlines=recommended_airlines,
        estimated_flight_cost_vnd=total_flight_cost_outbound,
        estimated_ticket_price_range=ticket_price_range,
        flight_arc_polyline=flight_arc_return,
        arc_coordinates=flight_arc_return
    )

    return_last_mile = get_ground_directions(
        origin_coords=(origin_airport.lat, origin_airport.lng),
        dest_coords=(origin_lat, origin_lng),
        vehicle=vehicle_type,
        origin_name=origin_airport.name,
        dest_name=origin_name,
        leg_type="last_mile"
    )

    # 6. Tạo Thẻ Timeline Sinh học
    outbound_cards, return_cards = generate_biological_timeline_cards(
        origin_airport=origin_airport,
        dest_airport=gateway_airport,
        first_mile=outbound_first_mile,
        flight=outbound_flight,
        last_mile=outbound_last_mile,
        origin_name=origin_name,
        dest_name=dest_name
    )

    # 7. Đóng gói Bản đồ Leaflet.js
    map_layers = {
        "markers": [
            {"type": "ORIGIN", "lat": origin_lat, "lng": origin_lng, "title": f"Xuất phát: {origin_name}"},
            {"type": "ORIGIN_AIRPORT", "lat": origin_airport.lat, "lng": origin_airport.lng, "iata": origin_airport.iata_code, "title": origin_airport.name},
            {"type": "GATEWAY_AIRPORT", "lat": gateway_airport.lat, "lng": gateway_airport.lng, "iata": gateway_airport.iata_code, "title": gateway_airport.name},
            {"type": "DESTINATION", "lat": dest_lat, "lng": dest_lng, "title": f"Điểm đến: {dest_name}"}
        ],
        "first_mile_polyline": outbound_first_mile.polyline,
        "flight_arc_polyline": outbound_flight.flight_arc_polyline,
        "last_mile_polyline": outbound_last_mile.polyline
    }

    # Tổng chi phí trung chuyển toàn bộ chuyến đi (Khứ hồi cả đường bộ + vé bay)
    total_transit_cost = (
        outbound_first_mile.estimated_cost_vnd +
        outbound_last_mile.estimated_cost_vnd +
        return_first_mile.estimated_cost_vnd +
        return_last_mile.estimated_cost_vnd +
        (total_flight_cost_outbound * 2)  # Vé khứ hồi
    )

    # Chuyến đi hoàn chỉnh
    outbound_journey = FlightTransitJourney(
        direction="outbound",
        first_mile=outbound_first_mile,
        flight_leg=outbound_flight,
        last_mile=outbound_last_mile,
        timeline_cards=outbound_cards,
        total_transit_duration_mins=(
            outbound_first_mile.duration_minutes + 105 + outbound_flight.flight_duration_minutes + 30 + outbound_last_mile.duration_minutes
        )
    )

    return_journey = FlightTransitJourney(
        direction="return",
        first_mile=return_first_mile,
        flight_leg=return_flight,
        last_mile=return_last_mile,
        timeline_cards=return_cards,
        total_transit_duration_mins=(
            return_first_mile.duration_minutes + 105 + return_flight.flight_duration_minutes + 30 + return_last_mile.duration_minutes
        )
    )

    return DoorToDoorFlightPipeline(
        is_flight_required=True,
        is_flight_applicable=True,
        interprovincial_distance_km=interprovincial_dist,
        origin_airport=origin_airport,
        destination_gateway_airport=gateway_airport,
        gateway_airport=gateway_airport,
        outbound_first_mile=outbound_first_mile,
        outbound_flight=outbound_flight,
        outbound_last_mile=outbound_last_mile,
        return_first_mile=return_first_mile,
        return_flight=return_flight,
        return_last_mile=return_last_mile,
        total_transit_cost_vnd=total_transit_cost,
        map_layers=map_layers,
        outbound_timeline_cards=outbound_cards,
        return_timeline_cards=return_cards,
        outbound=outbound_journey,
        return_journey=return_journey
    )


# ==============================================================================
# 9. TÍCH HỢP & LÀM GIÀU LỊCH TRÌNH (ENRICH PLAN WITH FLIGHT TRANSIT)
# ==============================================================================
def extract_destination_from_plan(
    plan: Dict[str, Any],
    db_path: str = "travel_db.db"
) -> Tuple[Optional[float], Optional[float], str, str]:
    """
    Trích xuất tọa độ GPS, tên điểm đến và tên tỉnh từ kết quả lịch trình:
    1. Kiểm tra tọa độ lat, lng trong day_steps của Ngày 1.
    2. Nếu chưa có, giải mã query parameters từ static_map_url.
    3. Tra cứu bảng places trong travel_db.db nếu cần.
    """
    days = plan.get("days", [])
    if not days:
        return None, None, "", ""

    day1 = days[0]
    itinerary = day1.get("itinerary", [])
    if not itinerary:
        return None, None, "", ""

    first_step = itinerary[0]
    dest_name = first_step.get("name", "Điểm đến Ngày 1")
    dest_addr = first_step.get("address", "")
    dest_lat = first_step.get("lat")
    dest_lng = first_step.get("lng")

    # Giải mã từ static_map_url nếu chưa có lat/lng
    if dest_lat is None or dest_lng is None:
        map_url = day1.get("static_map_url", "")
        match_orig = re.search(r"origin_lat=([0-9\.\-]+)&origin_lng=([0-9\.\-]+)", map_url)
        if match_orig:
            dest_lat = float(match_orig.group(1))
            dest_lng = float(match_orig.group(2))

    # Tra cứu DB nếu vẫn chưa có
    if dest_lat is None or dest_lng is None:
        try:
            real_db = resolve_db_path(db_path)
            conn = sqlite3.connect(real_db)
            c = conn.cursor()
            c.execute("SELECT lat, lng, address FROM places WHERE name = ? LIMIT 1", (dest_name,))
            row = c.fetchone()
            conn.close()
            if row:
                dest_lat = float(row[0])
                dest_lng = float(row[1])
                if not dest_addr and row[2]:
                    dest_addr = row[2]
        except Exception:
            pass

    # Xác định tỉnh từ địa chỉ hoặc tên
    dest_province = ""
    full_text = f"{dest_name} {dest_addr}"
    norm_full = normalize_text(full_text)

    # Danh mục kiểm tra tỉnh trọng điểm
    province_keywords = [
        ("quang nam", "Quảng Nam"),
        ("hoi an", "Quảng Nam"),
        ("da nang", "Đà Nẵng"),
        ("lao cai", "Lào Cai"),
        ("sa pa", "Lào Cai"),
        ("sapa", "Lào Cai"),
        ("binh thuan", "Bình Thuận"),
        ("mui ne", "Bình Thuận"),
        ("phan thiet", "Bình Thuận"),
        ("khanh hoa", "Khánh Hòa"),
        ("nha trang", "Khánh Hòa"),
        ("kien giang", "Kiên Giang"),
        ("phu quoc", "Kiên Giang"),
        ("lam dong", "Lâm Đồng"),
        ("da lat", "Lâm Đồng"),
        ("thua thien hue", "Thừa Thiên Huế"),
        ("hue", "Thừa Thiên Huế"),
        ("ninh binh", "Ninh Bình"),
        ("quang ninh", "Quảng Ninh"),
        ("ha long", "Quảng Ninh"),
        ("hai phong", "Hải Phòng"),
        ("can tho", "Cần Thơ"),
        ("ba ria vung tau", "Bà Rịa - Vũng Tàu"),
        ("vung tau", "Bà Rịa - Vũng Tàu"),
        ("binh dinh", "Bình Định"),
        ("quy nhon", "Bình Định"),
        ("phu yen", "Phú Yên"),
        ("tuy hoa", "Phú Yên"),
        ("dak lak", "Đắk Lắk"),
        ("buon ma thuot", "Đắk Lắk"),
        ("gia lai", "Gia Lai"),
        ("pleiku", "Gia Lai"),
        ("nghe an", "Nghệ An"),
        ("vinh", "Nghệ An"),
        ("thanh hoa", "Thanh Hóa"),
        ("quang binh", "Quảng Bình"),
        ("dong hoi", "Quảng Bình"),
        ("dien bien", "Điện Biên"),
        ("ca mau", "Cà Mau")
    ]

    for kw, prov in province_keywords:
        if kw in norm_full:
            dest_province = prov
            break

    return dest_lat, dest_lng, dest_name, dest_province

def enrich_plan_with_flight_transit(
    plan: Optional[Dict[str, Any]] = None,
    origin_coords: Optional[Tuple[float, float]] = None,
    origin_lat: Optional[float] = None,
    origin_lng: Optional[float] = None,
    origin_name: str = "Vị trí của bạn",
    dest_province: Optional[str] = None,
    prefer_flight: bool = False,
    vehicle_type: str = "car",
    plan_result: Optional[Dict[str, Any]] = None,
    db_path: str = "travel_db.db"
) -> Dict[str, Any]:
    """
    Hàm giao tiếp then chốt kết nối giữa lõi tính toán lịch trình và hành trình hàng không:
    - Nhận plan từ generate_multi_day_plan.
    - Nếu cự ly liên tỉnh < 300 km và không yêu cầu máy bay: Trả về plan NGUYÊN VẸN 100%.
    - Nếu thỏa mãn điều kiện bay:
      + Bổ sung trường gốc 'flight_transit' (DoorToDoorFlightPipeline).
      + Làm giàu Ngày 1 với 'flight_transit_outbound' kèm timeline_cards.
      + Làm giàu Ngày cuối với 'flight_transit_return' kèm timeline_cards.
      + Cập nhật tổng chi phí chuyến đi trong summary.
    """
    target_plan = plan if plan is not None else plan_result
    if target_plan is None:
        return {}

    # 1. Xác định tọa độ xuất phát
    if origin_coords is not None:
        resolved_origin = origin_coords
    elif origin_lat is not None and origin_lng is not None:
        resolved_origin = (origin_lat, origin_lng)
    else:
        # Fallback vị trí mặc định tại Trung tâm Hà Nội (Hồ Gươm) theo Tier 3 Fallback
        resolved_origin = (21.0285, 105.8542)
        if not origin_name or origin_name == "Vị trí của bạn":
            origin_name = "Hà Nội"

    # 2. Xác định điểm đến từ lịch trình
    extracted_lat, extracted_lng, dest_name, auto_province = extract_destination_from_plan(target_plan, db_path=db_path)
    if extracted_lat is None or extracted_lng is None:
        # Không đủ dữ liệu xác định điểm đến, giữ nguyên lịch trình
        return target_plan

    effective_province = dest_province or auto_province

    # 3. Lấy thông tin đoàn và phương tiện
    summary = target_plan.get("summary", {})
    group_size = summary.get("group_size", 2)
    effective_vehicle = summary.get("vehicle", vehicle_type)

    # 4. Xây dựng đường ống hành trình bay
    pipeline = build_flight_transit_pipeline(
        origin_coords=resolved_origin,
        dest_coords=(extracted_lat, extracted_lng),
        dest_province=effective_province,
        origin_name=origin_name,
        dest_name=dest_name,
        group_size=group_size,
        prefer_flight=prefer_flight,
        vehicle_type=effective_vehicle,
        db_path=db_path
    )

    # Nếu không thỏa mãn điều kiện bay (cự ly < 300 km): Giữ nguyên lịch trình
    if pipeline is None or not pipeline.is_flight_required:
        return target_plan

    # 5. Làm giàu cấu trúc dữ liệu trả về
    pipeline_dump = pipeline.model_dump()
    target_plan["flight_transit"] = pipeline_dump

    days = target_plan.get("days", [])
    if days:
        # Ngày 1: Gắn chặng bay lượt đi
        days[0]["flight_transit_outbound"] = {
            "first_mile": pipeline.outbound_first_mile.model_dump() if pipeline.outbound_first_mile else None,
            "flight": pipeline.outbound_flight.model_dump() if pipeline.outbound_flight else None,
            "last_mile": pipeline.outbound_last_mile.model_dump() if pipeline.outbound_last_mile else None,
            "timeline_cards": [c.model_dump() for c in (pipeline.outbound_timeline_cards or [])],
            "origin_airport": pipeline.origin_airport.model_dump() if pipeline.origin_airport else None,
            "gateway_airport": pipeline.destination_gateway_airport.model_dump() if pipeline.destination_gateway_airport else None
        }

        # Ngày cuối: Gắn chặng bay lượt về
        days[-1]["flight_transit_return"] = {
            "first_mile": pipeline.return_first_mile.model_dump() if pipeline.return_first_mile else None,
            "flight": pipeline.return_flight.model_dump() if pipeline.return_flight else None,
            "last_mile": pipeline.return_last_mile.model_dump() if pipeline.return_last_mile else None,
            "timeline_cards": [c.model_dump() for c in (pipeline.return_timeline_cards or [])],
            "origin_airport": pipeline.destination_gateway_airport.model_dump() if pipeline.destination_gateway_airport else None,
            "gateway_airport": pipeline.origin_airport.model_dump() if pipeline.origin_airport else None
        }

    # Cập nhật chi phí tổng hợp trong summary
    if summary:
        summary["flight_included"] = True
        summary["total_transit_cost_vnd"] = pipeline.total_transit_cost_vnd
        current_grand = summary.get("grand_total_group_vnd", 0)
        new_grand = current_grand + pipeline.total_transit_cost_vnd
        summary["grand_total_group_vnd"] = new_grand
        summary["grand_total_per_person_vnd"] = int(new_grand / max(1, group_size))

    return target_plan
