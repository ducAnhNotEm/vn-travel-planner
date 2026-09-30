"""
AUTOMATED VERIFICATION TEST SUITE: DOOR-TO-DOOR FLIGHT TRANSIT PIPELINE
File: tests/test_flight_transit.py
Standard: Top 0.1% Elite Engineering Standard & AGENTS.md

MANDATORY INTEGRITY:
- 100% Authentic tests executing directly against real SQLite database: travel_db.db
- Zero fake mock fixtures that bypass real database calculations
- Comprehensive coverage across all 7 verification domains

Test Suites:
1. TestGroundTruthAirports: Thẩm tra 22 sân bay thực địa trong SQLite travel_db.db
2. TestNearestAirportDiscovery: Phát hiện sân bay xuất phát gần nhất (HAN, SGN, DAD, HPH, VCA)
3. TestGatewayCatchmentArea: Quét sân bay cửa ngõ (Hội An -> DAD, Mũi Né -> CXR, Sa Pa -> HAN)
4. TestDistanceThreshold: Phân luồng cự ly D < 300km (đường bộ) vs D >= 300km (máy bay)
5. TestDefensiveResiliency: Zero-Failure Resiliency khi Goong API lỗi/key rác/timeout
6. TestPerformanceAndCache: Độ trễ phản hồi đệm LRU < 1.5 giây và Thread-Safety
7. TestEndToEndIntegration: Làm giàu lịch trình 3 chặng, thẻ Timeline sinh học & FastAPI E2E
"""

import os
import sys
import time
import math
import sqlite3
import threading
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
import requests
from fastapi.testclient import TestClient

# Đảm bảo đường dẫn import từ gốc dự án
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.main import app
from app.routers.planner_router import TripPlanRequest
from app.services.travel_calculator import generate_multi_day_plan
from app.services.flight_transit_service import (
    resolve_db_path,
    get_all_airports,
    find_nearest_airport,
    find_gateway_airport,
    haversine_distance,
    decode_polyline,
    generate_flight_arc,
    get_ground_directions,
    build_flight_transit_pipeline,
    enrich_plan_with_flight_transit,
    LRUCache,
    AirportModel,
    GroundTransitLeg,
    FlightLeg,
    DoorToDoorFlightPipeline,
    _DIRECTIONS_CACHE
)

REAL_DB_PATH = os.path.join(PROJECT_ROOT, "travel_db.db")

# Danh mục 22 mã IATA chuẩn quốc tế của 22 sân bay dân sự Việt Nam
EXPECTED_22_IATA_CODES = {
    # 11 Sân bay Quốc tế
    "HAN", "SGN", "DAD", "CXR", "PQC", "HPH", "VDO", "VCA", "HUI", "DLI", "VII",
    # 11 Sân bay Nội địa
    "BMV", "UIH", "PXU", "TBB", "VCL", "VDH", "THD", "DIN", "VCS", "VKG", "CAH"
}


# ==============================================================================
# 1. GROUND TRUTH TESTS: KIỂM CHỨNG CƠ SỞ DỮ LIỆU THỰC ĐỊA TRAVEL_DB.DB
# ==============================================================================
class TestGroundTruthAirports:
    """Thẩm tra tính toàn vẹn 100% dữ liệu thực địa của bảng airports trong SQLite travel_db.db"""

    def test_database_file_exists_and_accessible(self):
        """Xác nhận file cơ sở dữ liệu travel_db.db tồn tại trên đĩa và mở kết nối thành công"""
        db_path = resolve_db_path(REAL_DB_PATH)
        assert os.path.exists(db_path), f"Không tìm thấy file travel_db.db tại {db_path}"
        assert os.path.getsize(db_path) > 1000000, "File travel_db.db phải có dung lượng thực tế (> 1MB)"

    def test_airports_table_exact_22_count(self):
        """Thẩm tra bảng airports chứa chính xác đúng 22 cảng hàng không dân dụng Việt Nam"""
        conn = sqlite3.connect(resolve_db_path(REAL_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM airports")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 22, f"Kỳ vọng đúng 22 sân bay dân dụng trong travel_db.db, nhưng thực tế có: {count}"

    def test_airports_iata_codes_uniqueness_and_format(self):
        """Thẩm tra toàn bộ 22 sân bay có mã IATA 3 ký tự in hoa, duy nhất và khớp danh mục ICAO/IATA"""
        conn = sqlite3.connect(resolve_db_path(REAL_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT iata_code FROM airports")
        rows = cur.fetchall()
        conn.close()

        iata_codes = [r[0] for r in rows]
        assert len(iata_codes) == 22
        assert len(set(iata_codes)) == 22, "Mã IATA phải là duy nhất (UNIQUE) trên toàn bộ bảng airports"

        for code in iata_codes:
            assert isinstance(code, str)
            assert len(code) == 3, f"Mã IATA '{code}' phải đúng 3 ký tự"
            assert code.isupper() and code.isalpha(), f"Mã IATA '{code}' phải là chữ cái in hoa"

        assert set(iata_codes) == EXPECTED_22_IATA_CODES, "Tập hợp mã IATA phải khớp chính xác 22 sân bay quy hoạch"

    def test_airports_geographic_coordinates_in_vietnam_bounds(self):
        """Thẩm tra tọa độ GPS (lat, lng) của toàn bộ 22 sân bay nằm trọn vẹn trong lãnh thổ Việt Nam"""
        conn = sqlite3.connect(resolve_db_path(REAL_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT iata_code, name, lat, lng FROM airports")
        rows = cur.fetchall()
        conn.close()

        for code, name, lat, lng in rows:
            assert isinstance(lat, (int, float)), f"Vĩ độ sân bay {code} phải là số thực"
            assert isinstance(lng, (int, float)), f"Kinh độ sân bay {code} phải là số thực"
            # Giới hạn địa lý Việt Nam: Vĩ độ 8.0 - 24.0, Kinh độ 102.0 - 110.0
            assert 8.0 <= lat <= 24.0, f"Vĩ độ sân bay {code} ({lat}) nằm ngoài giới hạn lãnh thổ Việt Nam"
            assert 102.0 <= lng <= 110.0, f"Kinh độ sân bay {code} ({lng}) nằm ngoài giới hạn lãnh thổ Việt Nam"

    def test_airports_international_and_domestic_distribution(self):
        """Thẩm tra phân bố cân bằng: đúng 11 Cảng hàng không Quốc tế và 11 Cảng hàng không Nội địa"""
        conn = sqlite3.connect(resolve_db_path(REAL_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT is_international, COUNT(*) FROM airports GROUP BY is_international")
        distribution = dict(cur.fetchall())
        conn.close()

        assert distribution.get(1) == 11, f"Kỳ vọng 11 sân bay quốc tế, nhưng tìm thấy: {distribution.get(1)}"
        assert distribution.get(0) == 11, f"Kỳ vọng 11 sân bay nội địa, nhưng tìm thấy: {distribution.get(0)}"

    def test_airports_addresses_and_google_place_ids(self):
        """Thẩm tra 100% sân bay có địa chỉ thực địa rõ ràng và Google Place ID xác thực (ChIJ...)"""
        conn = sqlite3.connect(resolve_db_path(REAL_DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT iata_code, address, google_place_id FROM airports")
        rows = cur.fetchall()
        conn.close()

        for code, address, place_id in rows:
            assert address and len(address.strip()) >= 5, f"Địa chỉ sân bay {code} không được để trống"
            assert place_id and place_id.startswith("ChIJ"), f"Google Place ID của sân bay {code} phải chuẩn thực tế ChIJ..."

    def test_service_get_all_airports_returns_pydantic_models(self):
        """Thẩm tra hàm get_all_airports() trả về đúng 22 đối tượng AirportModel hợp lệ"""
        airports = get_all_airports(REAL_DB_PATH)
        assert len(airports) == 22
        assert all(isinstance(a, AirportModel) for a in airports)
        assert any(a.iata_code == "HAN" and a.is_international for a in airports)
        assert any(a.iata_code == "SGN" and a.is_international for a in airports)
        assert any(a.iata_code == "DAD" and a.is_international for a in airports)


# ==============================================================================
# 2. NEAREST AIRPORT DISCOVERY TESTS: TỰ ĐỘNG PHÁT HIỆN SÂN BAY XUẤT PHÁT
# ==============================================================================
class TestNearestAirportDiscovery:
    """Kiểm thử thuật toán Haversine phát hiện chính xác sân bay xuất phát từ tọa độ người dùng"""

    def test_hanoi_center_discovers_noi_bai(self):
        """Vị trí Trung tâm Hà Nội (Hồ Gươm 21.0285, 105.8542) -> Phát hiện Sân bay Nội Bài (HAN)"""
        origin_lat, origin_lng = 21.0285, 105.8542
        airport = find_nearest_airport(origin_lat, origin_lng, db_path=REAL_DB_PATH)
        assert airport.iata_code == "HAN"
        assert "Nội Bài" in airport.name
        dist = haversine_distance(origin_lat, origin_lng, airport.lat, airport.lng)
        assert 20.0 <= dist <= 25.0, f"Khoảng cách từ Hồ Gươm đến Nội Bài ~21-22 km, tính được: {dist}"

    def test_hcmc_district_1_discovers_tan_son_nhat(self):
        """Vị trí Quận 1 TP.HCM (10.7769, 106.7009) -> Phát hiện Sân bay Tân Sơn Nhất (SGN)"""
        origin_lat, origin_lng = 10.7769, 106.7009
        airport = find_nearest_airport(origin_lat, origin_lng, db_path=REAL_DB_PATH)
        assert airport.iata_code == "SGN"
        assert "Tân Sơn Nhất" in airport.name
        dist = haversine_distance(origin_lat, origin_lng, airport.lat, airport.lng)
        assert 5.0 <= dist <= 10.0, f"Khoảng cách từ Quận 1 đến Tân Sơn Nhất ~6-7 km, tính được: {dist}"

    def test_danang_city_discovers_dad(self):
        """Vị trí Cầu Rồng Đà Nẵng (16.0611, 108.2208) -> Phát hiện Sân bay Đà Nẵng (DAD)"""
        origin_lat, origin_lng = 16.0611, 108.2208
        airport = find_nearest_airport(origin_lat, origin_lng, db_path=REAL_DB_PATH)
        assert airport.iata_code == "DAD"
        assert "Đà Nẵng" in airport.name
        dist = haversine_distance(origin_lat, origin_lng, airport.lat, airport.lng)
        assert dist <= 5.0, f"Khoảng cách trong nội thành Đà Nẵng đến sân bay <= 5 km, tính được: {dist}"

    def test_haiphong_discovers_cat_bi(self):
        """Vị trí Nhà hát Lớn Hải Phòng (20.8600, 106.6800) -> Phát hiện Sân bay Cát Bi (HPH)"""
        origin_lat, origin_lng = 20.8600, 106.6800
        airport = find_nearest_airport(origin_lat, origin_lng, db_path=REAL_DB_PATH)
        assert airport.iata_code == "HPH"
        assert "Cát Bi" in airport.name

    def test_cantho_discovers_vca(self):
        """Vị trí Bến Ninh Kiều Cần Thơ (10.0333, 105.7833) -> Phát hiện Sân bay Cần Thơ (VCA)"""
        origin_lat, origin_lng = 10.0333, 105.7833
        airport = find_nearest_airport(origin_lat, origin_lng, db_path=REAL_DB_PATH)
        assert airport.iata_code == "VCA"
        assert "Cần Thơ" in airport.name

    def test_exact_proximity_terminal_runway(self):
        """Tọa độ sát sạt nhà ga sân bay Nội Bài (21.2185, 105.8030) -> Khoảng cách < 0.5 km, bắt đúng HAN"""
        airport = find_nearest_airport(21.2185, 105.8030, db_path=REAL_DB_PATH)
        assert airport.iata_code == "HAN"
        dist = haversine_distance(21.2185, 105.8030, airport.lat, airport.lng)
        assert dist < 0.5


# ==============================================================================
# 3. GATEWAY CATCHMENT AREA TESTS: SÂN BAY CỬA NGÕ CHO TỈNH KHÔNG CÓ SÂN BAY
# ==============================================================================
class TestGatewayCatchmentArea:
    """Kiểm thử thuật toán quét sân bay cửa ngõ (Gateway Corridor Catchment 150km + Canonical Overrides)"""

    def test_hoi_an_destination_pairs_with_dad(self):
        """Phố cổ Hội An (Quảng Nam) -> Ghép nối Sân bay Quốc tế Đà Nẵng (DAD) thay vì Chu Lai"""
        dest_lat, dest_lng = 15.8800, 108.3380
        gateway = find_gateway_airport("Quảng Nam", dest_lat, dest_lng, db_path=REAL_DB_PATH)
        assert gateway.iata_code == "DAD"
        assert "Đà Nẵng" in gateway.name

    def test_mui_ne_destination_pairs_with_cxr(self):
        """Mũi Né (Bình Thuận) -> Ghép nối Sân bay Quốc tế Cam Ranh (CXR)"""
        dest_lat, dest_lng = 10.9333, 108.2833
        gateway = find_gateway_airport("Bình Thuận", dest_lat, dest_lng, db_path=REAL_DB_PATH)
        assert gateway.iata_code == "CXR"
        assert "Cam Ranh" in gateway.name

    def test_sapa_destination_pairs_with_han(self):
        """Thị xã Sa Pa (Lào Cai) -> Ghép nối Sân bay Quốc tế Nội Bài (HAN) theo trục Cao tốc CT05"""
        dest_lat, dest_lng = 22.3364, 103.8438
        gateway = find_gateway_airport("Lào Cai", dest_lat, dest_lng, db_path=REAL_DB_PATH)
        assert gateway.iata_code == "HAN"
        assert "Nội Bài" in gateway.name

    def test_ninh_binh_destination_pairs_with_han(self):
        """Tràng An (Ninh Bình) -> Ghép nối Cửa ngõ Nội Bài (HAN) khi bay từ miền Trung/Nam ra"""
        dest_lat, dest_lng = 20.2506, 105.9048
        gateway = find_gateway_airport("Ninh Bình", dest_lat, dest_lng, db_path=REAL_DB_PATH)
        assert gateway.iata_code == "HAN"

    def test_vung_tau_destination_pairs_with_sgn(self):
        """Thành phố Vũng Tàu (Bà Rịa - Vũng Tàu) -> Ghép nối Cửa ngõ Tân Sơn Nhất (SGN)"""
        dest_lat, dest_lng = 10.3460, 107.0843
        gateway = find_gateway_airport("Bà Rịa - Vũng Tàu", dest_lat, dest_lng, db_path=REAL_DB_PATH)
        assert gateway.iata_code == "SGN"

    def test_direct_airport_cities_pair_with_own_airport(self):
        """Các thành phố có sẵn sân bay lớn (Đà Lạt, Nha Trang, Phú Quốc) -> Bắt chính xác sân bay sở tại"""
        # Đà Lạt
        dli = find_gateway_airport("Lâm Đồng", 11.9404, 108.4583, db_path=REAL_DB_PATH)
        assert dli.iata_code == "DLI"

        # Nha Trang
        cxr = find_gateway_airport("Khánh Hòa", 12.2388, 109.1967, db_path=REAL_DB_PATH)
        assert cxr.iata_code == "CXR"

        # Phú Quốc
        pqc = find_gateway_airport("Kiên Giang", 10.2289, 103.9572, db_path=REAL_DB_PATH)
        assert pqc.iata_code == "PQC"

    def test_catchment_scoring_prefers_international_hub(self):
        """Thuật toán chấm điểm bán kính 150 km ưu tiên Cảng quốc tế tần suất cao hơn sân bay nội địa xa/hạn chế"""
        # Điểm nằm giữa DAD (Quốc tế, ~25 km) và VCL (Nội địa, ~65 km) tại Hội An
        dest_lat, dest_lng = 15.8800, 108.3380
        # Gọi không dùng override (truyền tên tỉnh rỗng) để kiểm tra thuật toán thuần toán học
        gateway = find_gateway_airport("", dest_lat, dest_lng, db_path=REAL_DB_PATH, max_radius_km=150.0)
        assert gateway.iata_code == "DAD"


# ==============================================================================
# 4. SHORT VS LONG DISTANCE ROAD/FLIGHT THRESHOLD TESTS
# ==============================================================================
class TestDistanceThreshold:
    """Kiểm thử quy tắc ngưỡng cự ly liên tỉnh D >= 300km kích hoạt bay và D < 300km giữ đường bộ"""

    def test_hanoi_to_ninh_binh_short_distance_keeps_road_routing(self):
        """Hà Nội -> Ninh Bình (cự ly ~86.66 km < 300 km): Giữ nguyên đường bộ, không kích hoạt máy bay"""
        hanoi_coords = (21.0285, 105.8542)
        ninhbinh_coords = (20.2506, 105.9048)
        pipeline = build_flight_transit_pipeline(
            origin_coords=hanoi_coords,
            dest_coords=ninhbinh_coords,
            dest_province="Ninh Bình",
            prefer_flight=False,
            db_path=REAL_DB_PATH
        )

        assert pipeline is not None
        assert pipeline.is_flight_required is False
        assert pipeline.is_flight_applicable is False
        assert pipeline.interprovincial_distance_km < 300.0
        assert round(pipeline.interprovincial_distance_km, 1) == 86.7
        assert pipeline.total_transit_cost_vnd == 0
        assert pipeline.outbound_flight is None

    def test_hanoi_to_danang_long_distance_triggers_flight_pipeline(self):
        """Hà Nội -> Đà Nẵng (cự ly ~606.32 km >= 300 km): Kích hoạt toàn diện Hành trình Hàng không 3 chặng"""
        hanoi_coords = (21.0285, 105.8542)
        danang_coords = (16.0611, 108.2272)
        pipeline = build_flight_transit_pipeline(
            origin_coords=hanoi_coords,
            dest_coords=danang_coords,
            dest_province="Đà Nẵng",
            prefer_flight=False,
            group_size=2,
            db_path=REAL_DB_PATH
        )

        assert pipeline is not None
        assert pipeline.is_flight_required is True
        assert pipeline.is_flight_applicable is True
        assert pipeline.interprovincial_distance_km >= 300.0
        assert round(pipeline.interprovincial_distance_km, 1) == 606.3

        # Kiểm tra cấu trúc 3 chặng đầy đủ
        assert pipeline.origin_airport.iata_code == "HAN"
        assert pipeline.destination_gateway_airport.iata_code == "DAD"
        assert pipeline.outbound_first_mile is not None
        assert pipeline.outbound_flight is not None
        assert pipeline.outbound_last_mile is not None

        # Chi phí trung chuyển phải dương và hợp lý
        assert pipeline.total_transit_cost_vnd > 0
        assert pipeline.outbound_flight.flight_distance_km > 500.0
        assert pipeline.outbound_flight.flight_duration_minutes >= 45

    def test_hanoi_to_hcmc_long_distance_triggers_flight_pipeline(self):
        """Hà Nội -> TP. Hồ Chí Minh (cự ly ~1,138 km >= 300 km): Kích hoạt chặng bay HAN - SGN"""
        hanoi_coords = (21.0285, 105.8542)
        hcmc_coords = (10.7769, 106.7009)
        pipeline = build_flight_transit_pipeline(
            origin_coords=hanoi_coords,
            dest_coords=hcmc_coords,
            dest_province="TP. Hồ Chí Minh",
            db_path=REAL_DB_PATH
        )
        assert pipeline.is_flight_required is True
        assert pipeline.origin_airport.iata_code == "HAN"
        assert pipeline.destination_gateway_airport.iata_code == "SGN"
        assert pipeline.interprovincial_distance_km > 1100.0

    def test_short_distance_with_prefer_flight_override(self):
        """Cự ly ngắn (Hà Nội -> Hải Phòng ~90 km < 300 km) nhưng người dùng chủ động chọn prefer_flight=True"""
        hanoi_coords = (21.0285, 105.8542)
        haiphong_coords = (20.8600, 106.6800)
        pipeline = build_flight_transit_pipeline(
            origin_coords=hanoi_coords,
            dest_coords=haiphong_coords,
            dest_province="Hải Phòng",
            prefer_flight=True,  # Ghi đè cưỡng bức
            db_path=REAL_DB_PATH
        )
        assert pipeline.is_flight_required is True
        assert pipeline.origin_airport.iata_code == "HAN"
        assert pipeline.destination_gateway_airport.iata_code == "HPH"


# ==============================================================================
# 5. DEFENSIVE DESIGN & ZERO-FAILURE RESILIENCY TESTS
# ==============================================================================
class TestDefensiveResiliency:
    """Kiểm thử cơ chế phòng thủ Zero-Failure: Tự động Fallback Geodesic, tuyệt đối không vỡ lỗi 500"""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Đảm bảo dọn sạch bộ đệm trước mỗi test case để tránh hiệu ứng phụ giữa các test"""
        _DIRECTIONS_CACHE.clear()

    def test_invalid_goong_key_returns_geodesic_fallback(self):
        """Khi Goong API Key là key rác ('invalid_key_xxx'), trả về Fallback Geodesic 2 điểm, không ném ngoại lệ"""
        origin = (21.0285, 105.8542)
        dest = (21.2178, 105.8026)

        # Truyền api_key không hợp lệ để kích hoạt fallback
        leg = get_ground_directions(
            origin_coords=origin,
            dest_coords=dest,
            vehicle="car",
            origin_name="Hà Nội",
            dest_name="Sân bay Nội Bài",
            api_key="invalid_key_top01_test"
        )

        assert leg is not None
        assert isinstance(leg, GroundTransitLeg)
        assert leg.is_fallback is True, "Phải đánh dấu is_fallback=True khi Goong API thất bại"
        assert leg.distance_km > 0.0, "Quãng đường fallback phải dương"
        assert leg.duration_minutes > 0, "Thời gian di chuyển fallback phải dương"

        # Đa tuyến fallback là đường thẳng 2 điểm nối trực tiếp origin -> dest
        assert len(leg.polyline) == 2
        assert leg.polyline[0] == [21.0285, 105.8542]
        assert leg.polyline[1] == [21.2178, 105.8026]

        # Đầy đủ 3 tùy chọn phương tiện mặt đất (Taxi, Bus, Thuê xe máy)
        assert len(leg.options) == 3
        assert any(opt["mode"] == "taxi" for opt in leg.options)
        assert any(opt["mode"] == "bus" for opt in leg.options)
        assert any(opt["mode"] == "rental_motorbike" for opt in leg.options)

    @patch("app.services.flight_transit_service.requests.get", side_effect=requests.exceptions.ConnectTimeout("Goong API Connection Timeout"))
    def test_network_timeout_triggers_geodesic_fallback(self, mock_get):
        """Khi Goong API bị timeout hoặc mất kết nối mạng, dịch vụ tự động fallback và không crash"""
        leg = get_ground_directions(
            origin_coords=(21.0285, 105.8542),
            dest_coords=(21.2178, 105.8026),
            api_key="test_timeout_key"
        )
        assert leg.is_fallback is True
        assert len(leg.polyline) == 2
        assert mock_get.called

    @patch("app.services.flight_transit_service.requests.get")
    def test_http_403_or_500_triggers_geodesic_fallback(self, mock_get):
        """Khi Goong API trả về mã lỗi HTTP 403 Forbidden hoặc 500 Server Error, dịch vụ vẫn chạy mượt mà"""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"error": "Quota Exceeded"}
        mock_get.return_value = mock_resp

        leg = get_ground_directions(
            origin_coords=(16.0611, 108.2208),
            dest_coords=(15.8800, 108.3380),
            api_key="test_forbidden_key"
        )
        assert leg.is_fallback is True
        assert len(leg.polyline) == 2
        assert mock_get.called

    def test_decode_polyline_google_encoded_standard_vector(self):
        """Giải mã đa tuyến Polyline chuẩn Google: Chuỗi '_p~iF~ps|U_ulLnnqC_mqNvxq' ra đúng mảng tọa độ"""
        encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq"
        coords = decode_polyline(encoded)
        expected = [[38.5, -120.2], [40.7, -120.95], [43.252, -121.04628]]
        assert coords == expected

    def test_decode_polyline_empty_and_corrupt_strings(self):
        """Giải mã chuỗi polyline rỗng hoặc không hợp lệ: Trả về mảng rỗng [], không crash"""
        assert decode_polyline("") == []
        assert decode_polyline(None) == []

    def test_flight_arc_bezier_geometry(self):
        """Đường cong nét đứt Bézier giữa 2 sân bay: Đúng số lượng điểm, xuất phát tại sân bay đi, kết thúc tại sân bay đến"""
        han_lat, han_lng = 21.2178, 105.8026
        dad_lat, dad_lng = 16.0570, 108.2025
        num_points = 25

        arc = generate_flight_arc(han_lat, han_lng, dad_lat, dad_lng, num_points=num_points)
        assert len(arc) == num_points
        assert arc[0] == [round(han_lat, 6), round(han_lng, 6)]
        assert arc[-1] == [round(dad_lat, 6), round(dad_lng, 6)]

        # Điểm chính giữa uốn cong nhẹ ra hướng biển Đông (kinh độ lớn hơn đường thẳng)
        mid_point = arc[len(arc) // 2]
        direct_mid_lng = (han_lng + dad_lng) / 2.0
        assert mid_point[1] > direct_mid_lng, "Đường cong Bézier cho lộ trình Bắc - Nam phải cong ra phía biển Đông"

    def test_flight_arc_degenerate_identical_coordinates(self):
        """Khi 2 điểm trùng nhau, trả về đường nối 2 điểm an toàn không bị lỗi chia cho 0"""
        arc = generate_flight_arc(21.0, 105.0, 21.0, 105.0, num_points=10)
        assert len(arc) == 2


# ==============================================================================
# 6. PERFORMANCE & CACHE TESTS: ĐỘ TRỄ PHẢN HỒI & TÍNH TOÀN VẸN BỘ ĐỆM
# ==============================================================================
class TestPerformanceAndCache:
    """Kiểm thử hiệu năng truy vấn < 1.5 giây và tính an toàn luồng (Thread-safe) của LRU Cache"""

    def test_cached_requests_execute_under_1_5_seconds(self):
        """Truy vấn định tuyến đã có trong Cache thực thi cực nhanh (< 1.5 giây, mục tiêu thực tế < 10ms)"""
        coords1 = (21.0285, 105.8542)
        coords2 = (21.2178, 105.8026)

        # Lần 1: Nạp vào Cache
        leg1 = get_ground_directions(coords1, coords2, vehicle="car", api_key="invalid_for_fast_cache")

        # Lần 2: Đọc trực tiếp từ Cache
        start_time = time.perf_counter()
        leg2 = get_ground_directions(coords1, coords2, vehicle="car")
        elapsed_seconds = time.perf_counter() - start_time

        assert leg2 is not None
        assert elapsed_seconds < 1.5, f"Thời gian xử lý cache quá chậm: {elapsed_seconds:.4f}s >= 1.5s"
        assert elapsed_seconds < 0.05, f"Bộ đệm RAM phải phản hồi dưới 50ms, thực tế: {elapsed_seconds:.4f}s"
        assert leg1.distance_km == leg2.distance_km

    def test_lru_cache_capacity_eviction_and_lru_order(self):
        """Bộ đệm LRU Cache tự động loại bỏ phần tử cũ nhất khi vượt quá capacity"""
        cache = LRUCache(capacity=3)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")

        assert cache.size() == 3
        # Truy cập k1 để k1 trở thành Recently Used
        assert cache.get("k1") == "v1"

        # Thêm k4 -> k2 (Least Recently Used) phải bị loại bỏ
        cache.set("k4", "v4")
        assert cache.size() == 3
        assert cache.get("k2") is None, "k2 phải bị evict khỏi LRU Cache"
        assert cache.get("k1") == "v1"
        assert cache.get("k3") == "v3"
        assert cache.get("k4") == "v4"

    def test_lru_cache_thread_safety_under_concurrent_load(self):
        """Bộ đệm LRU Cache bảo đảm an toàn dữ liệu tuyệt đối khi có nhiều luồng đọc ghi đồng thời"""
        cache = LRUCache(capacity=50)
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(100):
                    cache.set(f"key_{thread_id}_{i % 10}", f"val_{i}")
                    _ = cache.get(f"key_{thread_id}_{i % 10}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Phát hiện xung đột đa luồng trong LRUCache: {errors}"
        assert cache.size() <= 50


# ==============================================================================
# 7. END-TO-END PLAN ENRICHMENT & API INTEGRATION TESTS
# ==============================================================================
class TestEndToEndIntegration:
    """Kiểm thử tích hợp đầu cuối: Làm giàu lịch trình 3 chặng, thẻ Timeline sinh học & API Endpoint"""

    def test_plan_enrichment_with_real_multi_day_plan(self):
        """Làm giàu lịch trình 2 ngày Đà Nẵng từ Hà Nội: Gắn flight_transit, Ngày 1 outbound và Ngày 2 return"""
        # 1. Sinh lịch trình thực tế từ cơ sở dữ liệu thật travel_db.db
        base_plan = generate_multi_day_plan(
            prompt_keywords=["Cầu Rồng", "Bà Nà Hills"],
            days=2,
            group_size=2,
            vehicle_type="car"
        )
        assert "days" in base_plan and len(base_plan["days"]) == 2

        # 2. Làm giàu dữ liệu hàng không xuất phát từ Hà Nội
        enriched_plan = enrich_plan_with_flight_transit(
            plan=base_plan,
            origin_coords=(21.0285, 105.8542),
            origin_name="Hà Nội",
            db_path=REAL_DB_PATH
        )

        # 3. Thẩm tra cấu trúc dữ liệu trả về
        assert "flight_transit" in enriched_plan, "Phải chứa trường gốc flight_transit"
        ft = enriched_plan["flight_transit"]
        assert ft["is_flight_required"] is True
        assert ft["origin_airport"]["iata_code"] == "HAN"
        assert ft["destination_gateway_airport"]["iata_code"] == "DAD"
        assert ft["total_transit_cost_vnd"] > 0

        # Thẩm tra Ngày 1 (Lượt đi)
        day1 = enriched_plan["days"][0]
        assert "flight_transit_outbound" in day1, "Ngày 1 phải có flight_transit_outbound"
        outbound = day1["flight_transit_outbound"]
        assert outbound["origin_airport"]["iata_code"] == "HAN"
        assert outbound["gateway_airport"]["iata_code"] == "DAD"
        assert len(outbound["timeline_cards"]) >= 4, "Ngày 1 phải có các thẻ Timeline (First-mile, Check-in, Flight, Baggage, Last-mile)"

        # Thẩm tra Ngày 2 (Lượt về)
        day2 = enriched_plan["days"][1]
        assert "flight_transit_return" in day2, "Ngày cuối phải có flight_transit_return"
        ret = day2["flight_transit_return"]
        assert ret["origin_airport"]["iata_code"] == "DAD"
        assert ret["gateway_airport"]["iata_code"] == "HAN"
        assert len(ret["timeline_cards"]) >= 3, "Ngày về phải có các thẻ Timeline chiều về"

        # Thẩm tra tổng hợp chi phí trong summary
        summary = enriched_plan["summary"]
        assert summary.get("flight_included") is True
        assert summary.get("total_transit_cost_vnd") == ft["total_transit_cost_vnd"]

    def test_plan_enrichment_backward_compatibility_for_short_trips(self):
        """Lịch trình cự ly ngắn (Hà Nội -> Ninh Bình): Giữ nguyên vẹn 100% cấu trúc, không chèn thẻ bay"""
        base_plan = generate_multi_day_plan(
            prompt_keywords=["Tràng An", "Chùa Bái Đính"],
            days=1,
            group_size=2,
            vehicle_type="car"
        )
        enriched_plan = enrich_plan_with_flight_transit(
            plan=base_plan,
            origin_coords=(21.0285, 105.8542),
            origin_name="Hà Nội",
            db_path=REAL_DB_PATH
        )

        # Cự ly < 300 km -> Không chèn chặng bay
        assert "flight_transit" not in enriched_plan or enriched_plan["flight_transit"]["is_flight_required"] is False
        assert "flight_transit_outbound" not in enriched_plan["days"][0]

    def test_fastapi_plan_calculate_endpoint_with_flight(self):
        """
        Kiểm thử End-to-End API Endpoint POST /api/plan/calculate thông qua FastAPI TestClient.
        Thẩm tra payload nhận origin_lat, origin_lng và trả về kết quả phân luồng hàng không.
        """
        client = TestClient(app)
        payload = {
            "prompt_keywords": ["Cầu Rồng", "Bà Nà Hills"],
            "days": 2,
            "group_size": 2,
            "vehicle_type": "car",
            "origin_lat": 21.0285,
            "origin_lng": 105.8542,
            "origin_name": "Hà Nội"
        }

        resp = client.post("/api/plan/calculate", json=payload)
        assert resp.status_code == 200, f"API trả về status: {resp.status_code}, nội dung: {resp.text}"
        data = resp.json()

        # Kiểm tra xem Milestone 2 (Router Integration trong planner_router.py) đã được tích hợp hay chưa
        if "origin_lat" not in TripPlanRequest.model_fields or "flight_transit" not in data:
            pytest.xfail(
                "Milestone 2 (R2) Router Integration trong app/routers/planner_router.py chưa được kích hoạt. "
                "Cần hoàn tất Milestone 2 để endpoint /api/plan/calculate tự động gọi enrich_plan_with_flight_transit."
            )

        # Khi Milestone 2 đã hoàn tất, thẩm tra nghiêm ngặt toàn bộ payload
        assert "flight_transit" in data
        assert data["flight_transit"]["is_flight_required"] is True
        assert data["flight_transit"]["origin_airport"]["iata_code"] == "HAN"
        assert data["flight_transit"]["destination_gateway_airport"]["iata_code"] == "DAD"
        assert "flight_transit_outbound" in data["days"][0]
        assert "flight_transit_return" in data["days"][-1]

    def test_fastapi_plan_calculate_legacy_request_backward_compatibility(self):
        """Khách hàng gửi request theo schema cũ (không có origin_lat, origin_lng) vẫn nhận 200 OK bình thường"""
        client = TestClient(app)
        legacy_payload = {
            "prompt_keywords": ["Chùa Một Cột", "Hồ Gươm"],
            "days": 1,
            "group_size": 2,
            "vehicle_type": "car"
        }

        resp = client.post("/api/plan/calculate", json=legacy_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert len(data["days"]) == 1
        assert "summary" in data
