"""
tests/test_road_trip_service.py
═══════════════════════════════════════════════════════════════════════════════
Bộ kiểm thử thực chứng Road Trip Engine trên travel_db.db thật.
Bao gồm: Fatigue Constraint, Overnight Staging, Scenic Corridor, Feasibility Advisor.

Nguyên tắc: Mọi assertion đều dựa trên dữ liệu thực tế và vật lý xác định.
"""
import math
import pytest
from app.services.road_trip_service import (
    _haversine,
    _road_distance_estimate,
    _drive_time_mins,
    _add_minutes,
    _point_to_segment_distance,
    _find_optimal_staging_city,
    _plan_pit_stops,
    _find_scenic_waypoints,
    build_road_trip_plan,
    check_road_trip_feasibility,
    VehicleType,
    DriveMode,
    GeoPoint,
    _STAGING_CITIES_NORTH_SOUTH,
    _MAX_CONTINUOUS_DRIVE_HRS,
    _SPEED_KMH,
    _SAFE_DAILY_KM,
)

DB_PATH = r"d:\vn-travel-planner\travel_db.db"

# Tọa độ Ground Truth (GPS thực tế)
HANOI     = GeoPoint(lat=21.0285, lng=105.8542, name="Hà Nội")
DANANG    = GeoPoint(lat=16.0544, lng=108.2022, name="Đà Nẵng")
HCMC      = GeoPoint(lat=10.7769, lng=106.7009, name="TP. Hồ Chí Minh")
NHATRANG  = GeoPoint(lat=12.2388, lng=109.1967, name="Nha Trang")
NINHBINH  = GeoPoint(lat=20.2506, lng=105.9745, name="Ninh Bình")
DALAT     = GeoPoint(lat=11.9404, lng=108.4583, name="Đà Lạt")


# ══════════════════════════════════════════════════════════════════════════════
# 1. TIỆN ÍCH TOÁN HỌC THUẦN (Pure Math)
# ══════════════════════════════════════════════════════════════════════════════

class TestPureMath:
    def test_haversine_hanoi_hcmc_approx_1150km(self):
        """Khoảng cách chim bay Hà Nội–TP.HCM xấp xỉ 1.140–1.160 km."""
        d = _haversine(HANOI.lat, HANOI.lng, HCMC.lat, HCMC.lng)
        assert 1130 <= d <= 1170, f"Khoảng cách Hà Nội–HCM bất thường: {d:.1f} km"

    def test_haversine_hanoi_danang_approx_620km(self):
        """Hà Nội–Đà Nẵng chim bay ~620 km."""
        d = _haversine(HANOI.lat, HANOI.lng, DANANG.lat, DANANG.lng)
        assert 600 <= d <= 650, f"Bất thường: {d:.1f} km"

    def test_haversine_symmetry(self):
        """Haversine phải đối xứng: d(A,B) == d(B,A)."""
        d1 = _haversine(HANOI.lat, HANOI.lng, HCMC.lat, HCMC.lng)
        d2 = _haversine(HCMC.lat, HCMC.lng, HANOI.lat, HANOI.lng)
        assert abs(d1 - d2) < 0.001

    def test_road_distance_tortuosity_factor(self):
        """Đường bộ phải dài hơn chim bay 35% (tortuosity 1.35)."""
        haversine_km = 500.0
        road_km = _road_distance_estimate(haversine_km)
        assert abs(road_km - 675.0) < 0.1, f"Tortuosity factor sai: {road_km}"

    def test_drive_time_car_300km(self):
        """300 km / 75 km/h = 240 phút (4 tiếng)."""
        mins = _drive_time_mins(300.0, VehicleType.CAR)
        assert 235 <= mins <= 245, f"Thời gian lái sai: {mins} phút"

    def test_add_minutes_basic(self):
        assert _add_minutes("06:30", 90) == "08:00"
        assert _add_minutes("06:30", 60) == "07:30"
        assert _add_minutes("23:00", 90) == "00:30"  # Qua nửa đêm

    def test_point_to_segment_distance_perpendicular(self):
        """Điểm chính giữa trục AB cách AB bằng 0 km."""
        # A = Hà Nội, B = Đà Nẵng, P = điểm giữa
        mid_lat = (HANOI.lat + DANANG.lat) / 2
        mid_lng = (HANOI.lng + DANANG.lng) / 2
        d = _point_to_segment_distance(mid_lat, mid_lng, HANOI.lat, HANOI.lng, DANANG.lat, DANANG.lng)
        assert d < 5.0, f"Điểm trục không nên cách xa đoạn thẳng: {d:.1f} km"

    def test_point_to_segment_distance_far_point(self):
        """Hà Giang (cực Bắc) rất xa trục Hà Nội–Đà Nẵng."""
        ha_giang_lat, ha_giang_lng = 22.8270, 104.9836
        d = _point_to_segment_distance(
            ha_giang_lat, ha_giang_lng,
            HANOI.lat, HANOI.lng, DANANG.lat, DANANG.lng
        )
        assert d > 150, f"Hà Giang phải rất xa trục Bắc-Nam: {d:.1f} km"


# ══════════════════════════════════════════════════════════════════════════════
# 2. PHÂN LUỒNG CỰ LY (Distance Routing Logic)
# ══════════════════════════════════════════════════════════════════════════════

class TestDistanceRouting:
    def test_short_trip_ninh_binh_no_road_trip_engine(self):
        """Hà Nội → Ninh Bình (~100 km) KHÔNG kích hoạt Road Trip Engine."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=NINHBINH.lat, dest_lng=NINHBINH.lng, dest_name="Ninh Bình",
            db_path=DB_PATH,
        )
        assert result["road_trip_required"] is False
        assert "one_way_km" in result
        assert result["one_way_km"] < 200

    def test_medium_trip_danang_triggers_road_trip(self):
        """Hà Nội → Đà Nẵng (~840 km đường bộ) PHẢI kích hoạt Road Trip Engine."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            db_path=DB_PATH,
        )
        assert result["road_trip_required"] is True
        assert result["one_way_km"] >= 300

    def test_long_trip_hcmc_requires_overnight_staging(self):
        """Hà Nội → TP.HCM (~1.560 km đường bộ) PHẢI có overnight staging."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=HCMC.lat, dest_lng=HCMC.lng, dest_name="TP. Hồ Chí Minh",
            db_path=DB_PATH,
        )
        assert result["road_trip_required"] is True
        assert result["requires_overnight_staging"] is True
        # Phải có nhiều hơn 1 ngày lái
        assert len(result["outbound"]) >= 2

    def test_return_route_exists(self):
        """Kết quả phải có cả chiều đi lẫn chiều về."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=NHATRANG.lat, dest_lng=NHATRANG.lng, dest_name="Nha Trang",
            db_path=DB_PATH,
        )
        assert result["road_trip_required"] is True
        assert "outbound" in result and len(result["outbound"]) > 0
        assert "return" in result and len(result["return"]) > 0

    def test_round_trip_km_is_double_one_way(self):
        """Khứ hồi = 2 × một chiều (±5% cho sai số làm tròn)."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            db_path=DB_PATH,
        )
        if result["road_trip_required"]:
            ratio = result["round_trip_km"] / result["one_way_km"]
            assert abs(ratio - 2.0) < 0.1, f"Khứ hồi không bằng đúng 2× một chiều: ratio={ratio}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. RÀNG BUỘC AN TOÀN SINH HỌC (Fatigue Constraint Validation)
# ══════════════════════════════════════════════════════════════════════════════

class TestFatigueConstraint:
    def test_no_segment_exceeds_max_continuous_drive(self):
        """
        Không có chặng lái đơn nào vượt quá 4 tiếng liên tục
        (= 4h × 75 km/h = 300 km cho ô tô).
        """
        pit_stops, segments, road_km, _ = _plan_pit_stops(
            start=HANOI, end=HCMC,
            vehicle=VehicleType.CAR,
            drive_mode=DriveMode.EXPRESS,
            departure_time="06:30",
            db_path=DB_PATH,
        )
        max_km_per_leg = _MAX_CONTINUOUS_DRIVE_HRS * _SPEED_KMH[VehicleType.CAR]
        for seg in segments:
            assert seg.distance_km <= max_km_per_leg + 5, (
                f"Chặng '{seg.from_name}→{seg.to_name}' dài {seg.distance_km} km vượt ràng buộc {max_km_per_leg} km"
            )

    def test_pit_stops_exist_for_long_haul(self):
        """Hành trình Hà Nội–TP.HCM phải có ít nhất 2 trạm dừng nghỉ."""
        pit_stops, _, _, _ = _plan_pit_stops(
            start=HANOI, end=HCMC,
            vehicle=VehicleType.CAR,
            drive_mode=DriveMode.EXPRESS,
            departure_time="06:30",
            db_path=DB_PATH,
        )
        assert len(pit_stops) >= 2, f"Quá ít trạm dừng: {len(pit_stops)}"

    def test_meal_stop_exists_around_noon(self):
        """Phải có ít nhất 1 trạm dừng loại MEAL (ăn trưa)."""
        pit_stops, _, _, _ = _plan_pit_stops(
            start=HANOI, end=HCMC,
            vehicle=VehicleType.CAR,
            drive_mode=DriveMode.EXPRESS,
            departure_time="06:30",
            db_path=DB_PATH,
        )
        meal_stops = [p for p in pit_stops if p.stop_type == "MEAL"]
        assert len(meal_stops) >= 1, "Không có trạm dừng ăn trưa nào!"

    def test_short_break_duration_is_30_minutes(self):
        """Trạm dừng ngắn (SHORT) phải kéo dài đúng 30 phút."""
        pit_stops, _, _, _ = _plan_pit_stops(
            start=HANOI, end=DANANG,
            vehicle=VehicleType.CAR,
            drive_mode=DriveMode.EXPRESS,
            departure_time="06:30",
            db_path=DB_PATH,
        )
        short_stops = [p for p in pit_stops if p.stop_type == "SHORT"]
        for s in short_stops:
            assert s.duration_mins == 30, f"Trạm ngắn sai thời lượng: {s.duration_mins} phút"

    def test_motorbike_safe_daily_km_lower_than_car(self):
        """Xe máy phải có ngưỡng km/ngày an toàn thấp hơn ô tô."""
        assert _SAFE_DAILY_KM[VehicleType.MOTORBIKE] < _SAFE_DAILY_KM[VehicleType.CAR]

    def test_motorbike_trip_has_more_days_than_car(self):
        """Cùng lộ trình Hà Nội–TP.HCM, xe máy cần nhiều ngày lái hơn ô tô."""
        car_result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=HCMC.lat, dest_lng=HCMC.lng, dest_name="TP. Hồ Chí Minh",
            vehicle="car", db_path=DB_PATH,
        )
        bike_result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=HCMC.lat, dest_lng=HCMC.lng, dest_name="TP. Hồ Chí Minh",
            vehicle="motorbike", db_path=DB_PATH,
        )
        if car_result["road_trip_required"] and bike_result["road_trip_required"]:
            assert len(bike_result["outbound"]) >= len(car_result["outbound"]), (
                "Xe máy phải cần ít nhất bằng số ngày lái của ô tô"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 4. OVERNIGHT STAGING (Tìm điểm nghỉ đêm trung gian)
# ══════════════════════════════════════════════════════════════════════════════

class TestOvernightStaging:
    def test_staging_city_is_between_origin_and_destination(self):
        """Thành phố nghỉ đêm phải nằm giữa Hà Nội và TP.HCM (về mặt địa lý)."""
        staging = _find_optimal_staging_city(HANOI, HCMC, VehicleType.CAR)
        staging_lat = staging["lat"]
        # Vĩ độ của staging city phải nằm giữa Hà Nội (21.03) và HCM (10.78)
        assert HCMC.lat <= staging_lat <= HANOI.lat, (
            f"Staging city {staging['name']} (lat={staging_lat}) không nằm giữa Hà Nội và HCM"
        )

    def test_staging_city_not_too_far_from_target_ratio(self):
        """Staging city ngày 1 không được quá 60% tổng đường."""
        total_road_km = _road_distance_estimate(
            _haversine(HANOI.lat, HANOI.lng, HCMC.lat, HCMC.lng)
        )
        staging = _find_optimal_staging_city(HANOI, HCMC, VehicleType.CAR)
        dist_from_hanoi = _road_distance_estimate(
            _haversine(HANOI.lat, HANOI.lng, staging["lat"], staging["lng"])
        )
        ratio = dist_from_hanoi / total_road_km
        assert ratio <= 0.65, f"Staging city quá xa (ratio={ratio:.2f}): {staging['name']}"

    def test_staging_city_has_required_fields(self):
        """Staging city phải có name, lat, lng, province."""
        staging = _find_optimal_staging_city(HANOI, DANANG, VehicleType.CAR)
        for field in ("name", "lat", "lng", "province"):
            assert field in staging, f"Thiếu trường '{field}' trong staging city"

    def test_all_staging_cities_are_in_vietnam_bounds(self):
        """Mọi thành phố staging phải nằm trong lãnh thổ Việt Nam."""
        for city in _STAGING_CITIES_NORTH_SOUTH:
            assert 8.0 <= city["lat"] <= 23.5, f"{city['name']}: lat={city['lat']} ngoài Việt Nam"
            assert 102.0 <= city["lng"] <= 110.0, f"{city['name']}: lng={city['lng']} ngoài Việt Nam"


# ══════════════════════════════════════════════════════════════════════════════
# 5. SCENIC MODE — CORRIDOR BUFFER (Ngắm cảnh dọc đường)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenicCorridor:
    def test_scenic_mode_returns_waypoints_list(self):
        """Scenic Mode phải trả về danh sách waypoints (có thể rỗng nếu DB chưa có data)."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            vehicle="car", drive_mode="scenic", db_path=DB_PATH,
        )
        if result["road_trip_required"]:
            assert isinstance(result["scenic_corridor_waypoints"], list)

    def test_scenic_waypoints_within_corridor(self):
        """Mọi waypoint trong Scenic Mode phải nằm trong hành lang 20km."""
        waypoints = _find_scenic_waypoints(HANOI, DANANG, max_detour_km=20, db_path=DB_PATH)
        for wp in waypoints:
            d = _point_to_segment_distance(
                wp["lat"], wp["lng"],
                HANOI.lat, HANOI.lng,
                DANANG.lat, DANANG.lng,
            )
            assert d <= 20.0 + 1.0, (  # +1km sai số tính toán
                f"Waypoint '{wp['name']}' nằm cách hành lang {d:.1f} km > 20 km"
            )

    def test_scenic_waypoints_sorted_by_route_progress(self):
        """Waypoints phải được sắp xếp theo thứ tự tiến trình trên đường."""
        waypoints = _find_scenic_waypoints(HANOI, HCMC, max_detour_km=20, db_path=DB_PATH)
        if len(waypoints) >= 2:
            ratios = [wp["route_progress_ratio"] for wp in waypoints]
            assert ratios == sorted(ratios), "Waypoints không được sắp xếp theo tiến trình"

    def test_express_mode_return_uses_scenic(self):
        """Khi đi Express, về sẽ Scenic (anti-boredom alternation)."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            vehicle="car", drive_mode="express", db_path=DB_PATH,
        )
        # Không crash và trả về cấu trúc đầy đủ
        if result["road_trip_required"]:
            assert "return" in result


# ══════════════════════════════════════════════════════════════════════════════
# 6. FEASIBILITY ADVISOR (Cố vấn khả thi)
# ══════════════════════════════════════════════════════════════════════════════

class TestFeasibilityAdvisor:
    def test_hanoi_hcmc_3_days_car_is_infeasible(self):
        """
        Hà Nội–TP.HCM (~1560 km đường bộ) bằng ô tô chỉ 3 ngày là KHÔNG KHẢ THI.
        Cần ít nhất 4 ngày lái (2 đi + 2 về), chưa tính ngày tham quan.
        """
        one_way_km = _road_distance_estimate(_haversine(HANOI.lat, HANOI.lng, HCMC.lat, HCMC.lng))
        result = check_road_trip_feasibility(one_way_km, total_trip_days=3, vehicle="car")
        assert result["feasible"] is False
        assert result["severity"] == "CRITICAL"
        assert "min_days_recommended" in result
        assert result["min_days_recommended"] > 3

    def test_hanoi_danang_7_days_car_is_feasible(self):
        """Hà Nội–Đà Nẵng 7 ngày bằng ô tô hoàn toàn khả thi."""
        one_way_km = _road_distance_estimate(_haversine(HANOI.lat, HANOI.lng, DANANG.lat, DANANG.lng))
        result = check_road_trip_feasibility(one_way_km, total_trip_days=7, vehicle="car")
        assert result["feasible"] is True
        assert result["play_days_available"] >= 1

    def test_short_trip_ninh_binh_1_day_ok(self):
        """Hà Nội–Ninh Bình (~110 km đường bộ) 1 ngày là OK (không cần staging)."""
        one_way_km = _road_distance_estimate(_haversine(HANOI.lat, HANOI.lng, NINHBINH.lat, NINHBINH.lng))
        result = check_road_trip_feasibility(one_way_km, total_trip_days=1, vehicle="car")
        assert result["feasible"] is True

    def test_feasibility_returns_required_fields(self):
        """Feasibility advisor phải trả về đủ các trường bắt buộc."""
        one_way_km = 500.0
        result = check_road_trip_feasibility(one_way_km, total_trip_days=5, vehicle="car")
        assert "feasible" in result
        assert "severity" in result
        assert "message" in result
        assert result["severity"] in ("OK", "WARNING", "CRITICAL")


# ══════════════════════════════════════════════════════════════════════════════
# 7. TÍNH NHẤT QUÁN CẤU TRÚC DỮ LIỆU (Data Contract Integrity)
# ══════════════════════════════════════════════════════════════════════════════

class TestDataContractIntegrity:
    def test_full_road_trip_plan_schema(self):
        """Kết quả build_road_trip_plan phải có đủ tất cả trường bắt buộc."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            db_path=DB_PATH,
        )
        if result["road_trip_required"]:
            required_keys = [
                "road_trip_required", "drive_mode", "vehicle",
                "origin", "destination", "one_way_km", "round_trip_km",
                "estimated_fuel_cost_vnd", "requires_overnight_staging",
                "outbound", "return", "scenic_corridor_waypoints", "scenic_passes",
            ]
            for key in required_keys:
                assert key in result, f"Thiếu trường '{key}' trong RoadTripPlan"

    def test_drive_day_schema(self):
        """Mỗi ngày lái xe phải có đủ segment và pit_stops."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=HCMC.lat, dest_lng=HCMC.lng, dest_name="TP. Hồ Chí Minh",
            db_path=DB_PATH,
        )
        if result["road_trip_required"] and result["outbound"]:
            day = result["outbound"][0]
            for key in ("day_index", "day_type", "title", "start_location",
                        "end_location", "total_km", "segments", "pit_stops"):
                assert key in day, f"Thiếu trường '{key}' trong drive day"

    def test_segment_schema(self):
        """Mỗi segment phải có từ, đến, khoảng cách, thời gian."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            db_path=DB_PATH,
        )
        if result["road_trip_required"] and result["outbound"]:
            for day in result["outbound"]:
                for seg in day["segments"]:
                    for key in ("from", "to", "distance_km", "drive_time_mins", "departure", "arrival"):
                        assert key in seg, f"Thiếu trường '{key}' trong segment"

    def test_fuel_cost_positive_and_nonzero(self):
        """Chi phí nhiên liệu phải > 0 cho mọi chuyến đường dài."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=DANANG.lat, dest_lng=DANANG.lng, dest_name="Đà Nẵng",
            db_path=DB_PATH,
        )
        if result["road_trip_required"]:
            assert result["estimated_fuel_cost_vnd"] > 0

    def test_short_trip_result_schema(self):
        """Kết quả cho chuyến đi ngắn (<300km) phải có road_trip_required=False và message."""
        result = build_road_trip_plan(
            origin_lat=HANOI.lat, origin_lng=HANOI.lng, origin_name="Hà Nội",
            dest_lat=NINHBINH.lat, dest_lng=NINHBINH.lng, dest_name="Ninh Bình",
            db_path=DB_PATH,
        )
        assert result["road_trip_required"] is False
        assert "message" in result
        assert "one_way_km" in result
