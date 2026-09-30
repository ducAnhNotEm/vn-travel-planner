"""
COMPREHENSIVE TSPTW ROUTING & 2-OPT VERIFICATION TEST SUITE
Standard: Top 0.1% Elite Engineering Standard & AGENTS.md
Test Verification Engineer: Milestone 3
Target System: app/services/travel_calculator.py & travel_db.db
"""

import os
import sys
import sqlite3
import time
import math
from typing import Dict, Any, List

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.main import app
from app.services.travel_calculator import (
    haversine_distance,
    get_terrain_factor,
    get_terrain_parameters,
    compute_travel_time,
    parse_dwell_time,
    parse_working_hours,
    parse_time_str,
    format_time_hhmm,
    format_intervals_display,
    resolve_place_working_hours,
    evaluate_intervals_for_visit,
    get_biological_period,
    simulate_route,
    optimize_route,
    solve_day_tsptw_2opt,
    sequence_by_human_rhythm,
    generate_multi_day_plan,
    generate_trip_plan,
)

client = TestClient(app)
DB_PATH = os.path.join(PROJECT_ROOT, "travel_db.db")


# ==============================================================================
# DATABASE FIXTURE HELPERS
# ==============================================================================
def get_db_place(place_id: int) -> Dict[str, Any]:
    """Trích xuất bản ghi thật từ travel_db.db theo id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, name, category, lat, lng, address, typical_time_spent, google_place_id
        FROM places WHERE id = ?
        """,
        (place_id,)
    )
    row = c.fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Place ID {place_id} not found in {DB_PATH}")
    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "lat": row[3],
        "lng": row[4],
        "address": row[5],
        "typical_time_spent": row[6],
        "google_place_id": row[7]
    }


def get_db_sample_places(limit: int = 10) -> List[Dict[str, Any]]:
    """Lấy N địa điểm thực tế từ travel_db.db phục vụ benchmark hiệu năng."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, name, category, lat, lng, address, typical_time_spent, google_place_id
        FROM places LIMIT ?
        """,
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "name": r[1],
            "category": r[2],
            "lat": r[3],
            "lng": r[4],
            "address": r[5],
            "typical_time_spent": r[6],
            "google_place_id": r[7]
        }
        for r in rows
    ]


# ==============================================================================
# SUITE 1: 2-OPT CROSSING-EDGE ELIMINATION
# ==============================================================================
class TestSuite1TwoOptCrossingElimination:
    """Kiểm tra giải thuật 2-Opt loại bỏ hoàn toàn các cung đường giao cắt chữ X."""

    def test_2opt_eliminates_crossing_edges_rectangle_vertices(self):
        """
        Kiểm tra 4 đỉnh hình chữ nhật tạo thành 2 đường chéo cắt nhau:
        Ban đầu: A(21.0, 105.0) -> C(21.1, 105.1) -> B(21.0, 105.1) -> D(21.1, 105.0)
        Đoạn AC và BD cắt nhau hình chữ X.
        2-Opt phải uncross về lộ trình chu vi [A, B, C, D] và giảm cự ly rõ rệt.
        """
        places_crossing = [
            {"name": "A", "lat": 21.0, "lng": 105.0},
            {"name": "C", "lat": 21.1, "lng": 105.1},
            {"name": "B", "lat": 21.0, "lng": 105.1},
            {"name": "D", "lat": 21.1, "lng": 105.0}
        ]

        initial_dist = (
            haversine_distance(21.0, 105.0, 21.1, 105.1) +
            haversine_distance(21.1, 105.1, 21.0, 105.1) +
            haversine_distance(21.0, 105.1, 21.1, 105.0)
        )

        opt_route, final_dist = optimize_route(places_crossing)
        opt_names = [p["name"] for p in opt_route]

        assert opt_names == ["A", "B", "C", "D"], (
            f"2-Opt phải gỡ giao cắt thành ['A', 'B', 'C', 'D'], nhận được: {opt_names}"
        )
        assert final_dist < initial_dist - 5.0, (
            f"Tổng quãng đường sau 2-Opt ({final_dist}km) phải giảm sâu so với ban đầu ({initial_dist:.2f}km)"
        )

    def test_2opt_eliminates_crossing_edges_six_nodes_star(self):
        """
        Kiểm tra 6 điểm với lộ trình ban đầu đan chéo phức tạp:
        Khẳng định optimize_route luôn tìm ra thứ tự có quãng đường ngắn hơn thứ tự cắt chéo.
        """
        star_places = [
            {"name": "P0", "lat": 21.00, "lng": 105.80},
            {"name": "P3", "lat": 21.06, "lng": 105.86},
            {"name": "P1", "lat": 21.02, "lng": 105.82},
            {"name": "P4", "lat": 21.08, "lng": 105.88},
            {"name": "P2", "lat": 21.04, "lng": 105.84},
            {"name": "P5", "lat": 21.10, "lng": 105.90}
        ]
        initial_dist = sum(
            haversine_distance(
                star_places[i]["lat"], star_places[i]["lng"],
                star_places[i+1]["lat"], star_places[i+1]["lng"]
            )
            for i in range(len(star_places) - 1)
        )

        opt_route, final_dist = optimize_route(star_places)
        assert len(opt_route) == 6
        assert final_dist < initial_dist, (
            f"Final distance ({final_dist} km) must be strictly less than crossing ({initial_dist:.2f} km)"
        )

    def test_2opt_preserves_pinned_nodes_anchor(self):
        """
        Kiểm tra Anchor-Based Clustering (AGENTS.md Điều 8):
        Các điểm có is_pinned=True không bị hoán đổi làm xáo trộn điểm chốt.
        """
        pinned_places = [
            {"name": "A", "lat": 21.0, "lng": 105.0, "is_pinned": True},
            {"name": "C", "lat": 21.1, "lng": 105.1},
            {"name": "B", "lat": 21.0, "lng": 105.1, "is_pinned": True},
            {"name": "D", "lat": 21.1, "lng": 105.0}
        ]
        opt_route, _ = optimize_route(pinned_places)
        # Điểm A là điểm đầu tiên có is_pinned=True
        assert opt_route[0]["name"] == "A"

    def test_2opt_already_straight_route_no_degradation(self):
        """Lộ trình thẳng hàng đã tối ưu sẵn không bị làm xấu đi."""
        straight_places = [
            {"name": f"P{i}", "lat": 21.0 + i * 0.05, "lng": 105.0 + i * 0.05}
            for i in range(5)
        ]
        expected_dist = sum(
            haversine_distance(
                straight_places[i]["lat"], straight_places[i]["lng"],
                straight_places[i+1]["lat"], straight_places[i+1]["lng"]
            )
            for i in range(4)
        )
        opt_route, dist = optimize_route(straight_places)
        assert [p["name"] for p in opt_route] == [f"P{i}" for i in range(5)]
        assert math.isclose(dist, round(expected_dist, 2), abs_tol=0.1)


# ==============================================================================
# SUITE 2: TOPOGRAPHIC VELOCITY MATRIX & K_TOPO PHYSICS
# ==============================================================================
class TestSuite2TopographicVelocityMatrix:
    """Kiểm tra ma trận địa hình Việt Nam (K_topo) và vận tốc bình quân (V_avg)."""

    def test_get_terrain_factor_provinces_classification(self):
        """Kiểm tra đúng hệ số K_topo theo tỉnh/vùng miền (AGENTS.md Điều 10)."""
        # 1. Đèo dốc Vùng cao / Tây Bắc / Tây Nguyên -> K_topo = 1.75
        mountain_provinces = [
            "Hà Giang", "Lào Cai", "Sa Pa", "Sơn La", "Mộc Châu",
            "Lai Châu", "Điện Biên", "Cao Bằng", "Lâm Đồng", "Đà Lạt", "Đắk Lắk"
        ]
        for p in mountain_provinces:
            assert get_terrain_factor(p) == 1.75, f"Province '{p}' must have K_topo=1.75"

        # 2. Duyên hải / Bán sơn địa -> K_topo = 1.35
        coastal_provinces = [
            "Đà Nẵng", "Khánh Hòa", "Nha Trang", "Bình Định", "Quy Nhơn",
            "Phú Quốc", "Quảng Ninh", "Hạ Long", "Thanh Hóa", "Nghệ An", "Bình Thuận"
        ]
        for p in coastal_provinces:
            assert get_terrain_factor(p) == 1.35, f"Province '{p}' must have K_topo=1.35"

        # 3. Đồng bằng / Đô thị lớn / Cao tốc -> K_topo = 1.25
        flat_provinces = ["Hà Nội", "Hồ Chí Minh", "TP.HCM", "Cần Thơ", "Bắc Ninh", "Hải Dương"]
        for p in flat_provinces:
            assert get_terrain_factor(p) == 1.25, f"Province '{p}' must have K_topo=1.25"

        # Fallback tỉnh không rõ
        assert get_terrain_factor(None) == 1.25
        assert get_terrain_factor("Unknown Region") == 1.25

    def test_get_terrain_parameters_cluster_recognition(self):
        """Kiểm tra nhận diện địa hình cụm địa điểm trong ngày."""
        mountain_cluster = [
            {"name": "Đỉnh Fansipan", "address": "Sa Pa, Lào Cai"},
            {"name": "Bản Cát Cát", "address": "Sa Pa, Lào Cai"}
        ]
        k_m, v_m = get_terrain_parameters(mountain_cluster)
        assert k_m == 1.75
        assert v_m == 35.0

        coastal_cluster = [
            {"name": "Bãi biển Mỹ Khê", "address": "Sơn Trà, Đà Nẵng"},
            {"name": "Bán đảo Sơn Trà", "address": "Đà Nẵng"}
        ]
        k_c, v_c = get_terrain_parameters(coastal_cluster)
        assert k_c == 1.35
        assert v_c == 55.0

        urban_cluster = [
            {"name": "Hồ Hoàn Kiếm", "address": "Hoàn Kiếm, Hà Nội"},
            {"name": "Văn Miếu - Quốc Tử Giám", "address": "Đống Đa, Hà Nội"}
        ]
        k_u, v_u = get_terrain_parameters(urban_cluster)
        assert k_u == 1.25
        assert v_u == 45.0

        empty_k, empty_v = get_terrain_parameters([])
        assert empty_k == 1.25
        assert empty_v == 45.0

    def test_topographic_travel_time_physics_duration(self):
        """
        Khẳng định quy luật vật lý: Cùng một khoảng cách trắc địa (30km):
        - Vùng đèo dốc Tây Bắc (K=1.75, V=35km/h) tốn 90 phút di chuyển.
        - Vùng đồng bằng đô thị (K=1.25, V=45km/h) chỉ tốn 50 phút di chuyển.
        Thời gian vùng núi phải strictly > vùng đồng bằng.
        """
        # Giả sử 2 điểm cách nhau xấp xỉ 30 km theo Haversine
        # Khoảng cách giữa (21.0, 105.8) và (21.27, 105.8) ~ 30 km
        lat1, lng1 = 21.0000, 105.8000
        lat2, lng2 = 21.2700, 105.8000
        d_hav = haversine_distance(lat1, lng1, lat2, lng2)
        assert 29.0 <= d_hav <= 31.0

        t_mountain = compute_travel_time(lat1, lng1, lat2, lng2, k_topo=1.75, v_avg=35.0)
        t_coastal = compute_travel_time(lat1, lng1, lat2, lng2, k_topo=1.35, v_avg=55.0)
        t_flat = compute_travel_time(lat1, lng1, lat2, lng2, k_topo=1.25, v_avg=45.0)

        assert t_mountain > t_flat, f"Mountain time ({t_mountain}m) must be > Flat time ({t_flat}m)"
        assert t_mountain > t_coastal, f"Mountain time ({t_mountain}m) must be > Coastal time ({t_coastal}m)"
        assert t_mountain >= 88, f"Mountain 30km travel time should be ~90 mins, got {t_mountain}"
        assert t_flat <= 55, f"Flat 30km travel time should be ~50 mins, got {t_flat}"

    def test_travel_time_boundary_conditions(self):
        """Kiểm tra điều kiện biên của compute_travel_time (<1m và <500m)."""
        # Cự ly < 1m -> thời gian = 0
        assert compute_travel_time(21.0, 105.0, 21.0, 105.0) == 0

        # Cự ly ~ 200m -> thời gian tối thiểu 3 phút (đón/trả khách)
        # 0.001 độ vĩ ~ 111m -> 0.002 độ ~ 222m
        t_short = compute_travel_time(21.0000, 105.0000, 21.0020, 105.0000)
        assert t_short == 3, f"Short distance < 500m must return minimum 3 minutes, got {t_short}"


# ==============================================================================
# SUITE 3: HARD TIME-WINDOW FORWARD SIMULATION CORRECTNESS
# ==============================================================================
class TestSuite3HardTimeWindowForwardSimulation:
    """Kiểm tra tính chính xác của hệ phương trình mô phỏng xuôi dòng thời gian."""

    def test_dwell_time_regex_parsing(self):
        """Kiểm tra hàm parse_dwell_time với các định dạng tiếng Việt thực tế."""
        assert parse_dwell_time("90 phút") == 90
        assert parse_dwell_time("60 phút") == 60
        assert parse_dwell_time("75 phút") == 75
        assert parse_dwell_time("1 giờ") == 60
        assert parse_dwell_time("2 giờ") == 120
        assert parse_dwell_time("1h - 2h") == 90
        assert parse_dwell_time("1 - 2 giờ") == 90
        assert parse_dwell_time("2h - 4h") == 180
        assert parse_dwell_time("30 phút - 1 giờ") == 45
        assert parse_dwell_time("30 - 45 phút") == 37
        assert parse_dwell_time("Overnight") == 105
        assert parse_dwell_time("Lưu trú / Nghỉ đêm") == 105

        # Fallback khi None theo Category
        assert parse_dwell_time(None, "TEMPLE") == 90
        assert parse_dwell_time(None, "HISTORICAL_SITE") == 90
        assert parse_dwell_time(None, "RESTAURANT") == 75
        assert parse_dwell_time(None, "HOTEL") == 105
        assert parse_dwell_time(None, "MARKET") == 60
        assert parse_dwell_time(None, "CAFE") == 45
        assert parse_dwell_time(None, "ATTRACTION") == 60

    def test_parse_working_hours_intervals(self):
        """Kiểm tra parse_working_hours với các dạng ca đơn, ca đôi, 24/7."""
        # Ca đơn
        h1 = parse_working_hours("08:00 to 17:00")
        assert h1 == [(480, 1020)]

        # Ca đôi có giờ nghỉ trưa
        h2 = parse_working_hours("07:30 to 11:30, 13:30 to 17:30")
        assert h2 == [(450, 690), (810, 1050)]

        # Chợ đêm mở muộn
        h3 = parse_working_hours("17:30 to 23:45")
        assert h3 == [(1050, 1425)]

        # 24/7 / Cả ngày
        assert parse_working_hours("Mở cửa cả ngày (24/7)") == [(0, 1440)]
        assert parse_working_hours("24 hours") == [(0, 1440)]
        assert parse_working_hours(None) == []

    def test_forward_simulation_mathematical_invariants(self):
        """
        Kiểm tra các bất biến toán học của chuỗi thời gian xuôi dòng:
        1. Arrival_j = EstimatedArrival_j + WaitTime_j = max(Open_j, Departure_i + TravelTime_i_j)
        2. Departure_j = Arrival_j + Dwell_j
        3. suggested_time == arrival_time
        4. is_time_window_valid == (Departure_j <= Close_j)
        """
        p1 = {
            "name": "Điểm Khởi Hành",
            "category": "ATTRACTION",
            "lat": 21.0200, "lng": 105.8000,
            "working_hours": "08:00 to 12:00",
            "typical_time_spent": "60 phút"
        }
        p2 = {
            "name": "Điểm Tiếp Theo Mở Muộn",
            "category": "ATTRACTION",
            "lat": 21.0300, "lng": 105.8100,
            "working_hours": "10:30 to 17:00",
            "typical_time_spent": "60 phút"
        }
        places = [p1, p2]

        sim, is_valid, total_d = simulate_route(places, start_time_minutes=480)
        assert is_valid is True
        assert len(sim) == 2

        s1, s2 = sim[0], sim[1]
        assert s1["arrival_time"] == "08:00"
        assert s1["departure_time"] == "09:00"
        assert s1["dwell_time_minutes"] == 60
        assert s1["suggested_time"] == s1["arrival_time"]

        # Khoảng cách giữa 2 điểm ~ 1.5 km -> travel time ~ 3-4 phút
        # Khởi hành s1 lúc 09:00 -> đến s2 lúc ~ 09:04
        # Nhưng s2 mở cửa lúc 10:30 (630 phút)
        # Wait time phải là 10:30 - 09:04 = 86 phút!
        # Do đó arrival_time của s2 phải là 10:30!
        assert s2["arrival_time"] == "10:30"
        assert s2["departure_time"] == "11:30"
        assert s2["wait_time_minutes"] >= 80
        assert s2["suggested_time"] == s2["arrival_time"]
        assert s2["is_time_window_valid"] is True


# ==============================================================================
# SUITE 4: 5 GROUND-TRUTH REAL SCENARIOS FROM travel_db.db
# ==============================================================================
class TestSuite4GroundTruthRealScenarios:
    """Kiểm tra 5 kịch bản thực địa từ travel_db.db theo Mục 6 SPEC-TSPTW."""

    def test_case_1_night_market_late_opening_son_tra(self):
        """
        Ca 1: Chợ Đêm Sơn Trà (ID 1865, mở cửa 17:30 - 23:45).
        Lộ trình kết hợp điểm tham quan ban ngày (Bãi biển Mỹ Khê, Bảo tàng Chăm).
        Khẳng định Chợ Đêm Sơn Trà BẮT BUỘC được xếp vào buổi tối (Arrival >= 17:30),
        tuyệt đối không bị xếp vào buổi sáng như thuật toán cũ.
        """
        p_sontra = get_db_place(1865)
        p_cham = get_db_place(1446)
        p_mykhe = {
            "id": 99991,
            "name": "Bãi biển Mỹ Khê",
            "category": "ATTRACTION",
            "lat": 16.060,
            "lng": 108.245,
            "address": "Phước Mỹ, Sơn Trà, Đà Nẵng",
            "typical_time_spent": "90 phút"
        }

        # Cụm điểm ban ngày + chợ đêm
        day_places = [p_mykhe, p_cham, p_sontra]
        sim_route, dist = solve_day_tsptw_2opt(day_places, start_time_str="08:30")

        sontra_step = next(s for s in sim_route if s["id"] == 1865)
        arr_min = parse_time_str(sontra_step["arrival_time"])
        dep_min = parse_time_str(sontra_step["departure_time"])

        assert arr_min >= parse_time_str("17:30"), (
            f"Chợ Đêm Sơn Trà must be scheduled at or after 17:30, got {sontra_step['arrival_time']}"
        )
        assert sontra_step["is_time_window_valid"] is True
        # Khẳng định Chợ đêm nằm ở cuối lộ trình và các điểm tham quan ban ngày được xếp buổi sáng
        assert sim_route[-1]["id"] == 1865, "Chợ Đêm Sơn Trà must be sequenced as the final stop of the day"
        assert parse_time_str(sim_route[0]["arrival_time"]) < parse_time_str("12:00"), (
            "Daytime sightseeing places must be scheduled in the morning"
        )

    def test_case_2_heritage_site_lunch_break_quan_su(self):
        """
        Ca 2: Chùa Quán Sứ (ID 1012, mở cửa 07:30 - 11:30 và 13:30 - 17:30).
        Khẳng định thời gian tham quan chùa Quán Sứ hoàn tất trước 11:30 hoặc bắt đầu sau 13:30,
        tuyệt đối không có phút tham quan nào rơi vào khoảng cấm đóng cổng nghỉ trưa (11:30 - 13:30).
        """
        p_quansu = get_db_place(1012)
        p_hoangthanh = get_db_place(1001)
        p_dackim = get_db_place(2264)

        day_places = [p_hoangthanh, p_quansu, p_dackim]
        sim_route, _ = solve_day_tsptw_2opt(day_places, start_time_str="08:00")

        quansu_step = next(s for s in sim_route if s["id"] == 1012)
        q_arr = parse_time_str(quansu_step["arrival_time"])
        q_dep = parse_time_str(quansu_step["departure_time"])

        no_lunch_overlap = (q_dep <= parse_time_str("11:30")) or (q_arr >= parse_time_str("13:30"))
        assert no_lunch_overlap, (
            f"Chùa Quán Sứ visit ({quansu_step['arrival_time']} to {quansu_step['departure_time']}) "
            f"must NOT overlap with midday closure 11:30 - 13:30!"
        )
        assert quansu_step["is_time_window_valid"] is True

    def test_case_3_scenic_spot_sunset_closing_hoang_thanh(self):
        """
        Ca 3: Hoàng thành Thăng Long (ID 1001, đóng cửa lúc 17:00).
        Khẳng định du khách kết thúc tham quan trước hoặc đúng 17:00 (Departure <= 17:00).
        """
        p_hoangthanh = get_db_place(1001)
        p_quansu = get_db_place(1012)
        p_dackim = get_db_place(2264)

        day_places = [p_hoangthanh, p_quansu, p_dackim]
        sim_route, _ = solve_day_tsptw_2opt(day_places, start_time_str="08:00")

        ht_step = next(s for s in sim_route if s["id"] == 1001)
        ht_dep = parse_time_str(ht_step["departure_time"])

        assert ht_dep <= parse_time_str("17:00"), (
            f"Hoàng thành Thăng Long must depart by 17:00, got {ht_step['departure_time']}"
        )
        assert ht_step["is_time_window_valid"] is True

    def test_case_4_fixed_lunch_restaurant_dac_kim_and_ga_doi(self):
        """
        Ca 4: Nhà hàng ăn trưa cố định:
        - Bún Chả Đắc Kim (ID 2264, Hà Nội)
        - Nhà Hàng Gà Đồi Điện Biên (ID 2155, Khánh Hòa)
        Khẳng định thời gian đến ăn trưa rơi vào khung 11:30 - 13:30.
        """
        # Test Hà Nội với Bún Chả Đắc Kim
        p_dackim = get_db_place(2264)
        p_hoangthanh = get_db_place(1001)
        p_quansu = get_db_place(1012)

        day_hn = [p_hoangthanh, p_quansu, p_dackim]
        sim_hn, _ = solve_day_tsptw_2opt(day_hn, start_time_str="08:00")

        dk_step = next(s for s in sim_hn if s["id"] == 2264)
        dk_arr = parse_time_str(dk_step["arrival_time"])
        assert parse_time_str("11:30") <= dk_arr <= parse_time_str("13:30"), (
            f"Bún Chả Đắc Kim arrival must be in lunch window 11:30 - 13:30, got {dk_step['arrival_time']}"
        )
        assert dk_step["is_time_window_valid"] is True

        # Test Khánh Hòa với Gà Đồi Điện Biên (ID 2155)
        p_gadoi = get_db_place(2155)
        p_sight = {
            "id": 99992,
            "name": "Tháp Bà Ponagar Nha Trang",
            "category": "HISTORICAL_SITE",
            "lat": 12.2654,
            "lng": 109.1958,
            "address": "2 Tháng 4, Vĩnh Phước, Nha Trang, Khánh Hòa",
            "typical_time_spent": "90 phút"
        }
        day_nt = [p_sight, p_gadoi]
        sim_nt, _ = solve_day_tsptw_2opt(day_nt, start_time_str="09:00")
        gd_step = next(s for s in sim_nt if s["id"] == 2155)
        gd_arr = parse_time_str(gd_step["arrival_time"])
        assert parse_time_str("11:30") <= gd_arr <= parse_time_str("13:30"), (
            f"Gà Đồi Điện Biên arrival must be in lunch window 11:30 - 13:30, got {gd_step['arrival_time']}"
        )
        assert gd_step["is_time_window_valid"] is True

    def test_case_5_impossible_time_window_conflict_graceful_advisory(self):
        """
        Ca 5: Xung đột bất khả thi (Adversarial Infeasible Input):
        Người dùng ghim Chợ Đêm Sơn Trà (18:00) rồi mới đi Bảo tàng Chăm (đóng cửa 17:00).
        Quy trình phòng thủ Zero-Failure Resiliency:
        1. Không throw exception hay crash HTTP 500.
        2. Đánh dấu is_time_window_valid = False.
        3. Trường time_window_advisory kích hoạt cảnh báo thông minh (Smart Advisory Card).
        """
        p_sontra = get_db_place(1865)
        p_cham = get_db_place(1446)

        forced_places = [
            dict(p_sontra, pin_time="18:00", is_pinned=True),
            dict(p_cham, is_pinned=True)
        ]

        sim_route, all_valid, _ = simulate_route(forced_places)

        assert all_valid is False, "Overall route must be marked invalid when conflict occurs"
        cham_step = sim_route[1]
        assert cham_step["is_time_window_valid"] is False, "Cham Museum step must have is_time_window_valid=False"
        assert cham_step["time_window_advisory"] is not None
        assert "Xung đột thời gian" in cham_step["time_window_advisory"]
        assert "quá giờ" in cham_step["time_window_advisory"]


# ==============================================================================
# SUITE 5: CPU LATENCY BENCHMARK
# ==============================================================================
class TestSuite5CpuLatencyBenchmark:
    """Đo lường thời gian thực thi của giải thuật TSPTW 2-Opt trên CPU."""

    def test_tsptw_execution_latency_under_15ms(self):
        """
        Thẩm định hiệu năng:
        Quy mô N = 10 địa điểm thực tế từ travel_db.db chạy lặp 100 lần.
        Khẳng định độ trễ bình quân < 15ms / lần chạy.
        """
        sample_10 = get_db_sample_places(10)
        assert len(sample_10) == 10

        # Khởi động / warm-up bộ nhớ cache
        _ = solve_day_tsptw_2opt(sample_10)

        iterations = 100
        t_start = time.perf_counter()
        for _ in range(iterations):
            _ = solve_day_tsptw_2opt(sample_10)
        t_end = time.perf_counter()

        total_time_ms = (t_end - t_start) * 1000.0
        avg_latency_ms = total_time_ms / iterations

        print(
            f"\n[BENCHMARK] TSPTW 2-Opt CPU Latency for N=10 over {iterations} runs: "
            f"Total = {total_time_ms:.2f}ms | Avg = {avg_latency_ms:.2f}ms/run"
        )

        assert avg_latency_ms < 15.0, (
            f"Average latency ({avg_latency_ms:.2f}ms) must strictly meet the < 15ms budget!"
        )

    def test_latency_scaling_across_cluster_sizes(self):
        """Kiểm tra thời gian xử lý khi N = 3, N = 5, N = 8 đều < 15ms."""
        for n in [3, 5, 8]:
            sample = get_db_sample_places(n)
            t0 = time.perf_counter()
            _ = solve_day_tsptw_2opt(sample)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            assert elapsed_ms < 15.0, f"Cluster size N={n} took {elapsed_ms:.2f}ms, expected < 15ms"


# ==============================================================================
# SUITE 6: API & FRONTEND BACKWARD COMPATIBILITY SCHEMA CONTRACT
# ==============================================================================
class TestSuite6SchemaContractAndBackwardCompatibility:
    """Kiểm tra hợp đồng dữ liệu đầu ra và tương thích ngược 100%."""

    def test_generate_multi_day_plan_schema_fields(self):
        """
        Kiểm tra cấu trúc trả về của generate_multi_day_plan:
        Mỗi step trong itinerary phải có đầy đủ các trường cũ và các trường mới (P0).
        """
        plan = generate_multi_day_plan(["Hà Nội", "Hoàn Kiếm"], days=2, group_size=4, vehicle_type="car")

        assert "summary" in plan
        assert "days" in plan
        assert "itinerary" in plan
        assert len(plan["days"]) == 2

        required_step_keys = {
            "step", "name", "category", "suggested_time", "time",
            "arrival_time", "departure_time", "dwell_time_minutes",
            "wait_time_minutes", "is_time_window_valid", "time_window_display",
            "time_window_advisory", "open_time", "close_time",
            "period_name", "period_icon", "address", "lat", "lng",
            "rating", "price_display", "price_info"
        }

        for day in plan["days"]:
            assert "itinerary" in day
            for step in day["itinerary"]:
                missing_keys = required_step_keys - set(step.keys())
                assert not missing_keys, f"Missing required step keys: {missing_keys}"

                # Khẳng định tính tương thích ngược quan trọng
                assert step["suggested_time"] == step["arrival_time"], (
                    "suggested_time must equal arrival_time for frontend compatibility"
                )
                assert step["time"] == step["arrival_time"], (
                    "time must equal arrival_time for legacy consumers"
                )
                assert isinstance(step["is_time_window_valid"], bool)
                assert isinstance(step["dwell_time_minutes"], int)
                assert isinstance(step["wait_time_minutes"], int)

    def test_api_calculate_plan_endpoint_post(self):
        """
        Gọi trực tiếp HTTP POST /api/plan/calculate thông qua TestClient:
        Kiểm tra HTTP 200 và cấu trúc payload json trả về.
        """
        payload = {
            "prompt_keywords": ["Đà Nẵng", "Sơn Trà"],
            "days": 1,
            "group_size": 2,
            "vehicle_type": "car"
        }
        response = client.post("/api/plan/calculate", json=payload)
        assert response.status_code == 200, f"API returned {response.status_code}: {response.text}"

        data = response.json()
        assert "days" in data
        assert "itinerary" in data
        assert len(data["days"]) >= 1

        day_0 = data["days"][0]
        assert len(day_0["itinerary"]) >= 1

        first_step = day_0["itinerary"][0]
        assert "arrival_time" in first_step
        assert "departure_time" in first_step
        assert "suggested_time" in first_step
        assert first_step["suggested_time"] == first_step["arrival_time"]
        assert "dwell_time_minutes" in first_step
        assert "is_time_window_valid" in first_step


# ==============================================================================
# SUITE 7: ADVERSARIAL EDGE CASES & BOUNDARY CONDITIONS
# ==============================================================================
class TestSuite7AdversarialEdgeCases:
    """Kiểm tra các trường hợp biên, dữ liệu dị thường và phòng thủ lỗi."""

    def test_empty_places_handling_all_functions(self):
        """Danh sách rỗng không bao giờ gây crash."""
        assert optimize_route([]) == ([], 0.0)
        assert solve_day_tsptw_2opt([]) == ([], 0.0)
        assert simulate_route([]) == ([], True, 0.0)
        assert sequence_by_human_rhythm([]) == []

    def test_single_place_handling(self):
        """Một địa điểm duy nhất được xử lý an toàn."""
        p = {
            "id": 1,
            "name": "Single Attraction",
            "category": "ATTRACTION",
            "lat": 21.0,
            "lng": 105.0,
            "address": "Hà Nội"
        }
        opt_route, dist = optimize_route([p])
        assert len(opt_route) == 1
        assert dist == 0.0

        tsptw_route, dist_tsptw = solve_day_tsptw_2opt([p])
        assert len(tsptw_route) == 1
        assert dist_tsptw == 0.0
        assert "arrival_time" in tsptw_route[0]

        seq_route = sequence_by_human_rhythm([p])
        assert len(seq_route) == 1

    def test_malformed_working_hours_strings_safe_fallback(self):
        """Chuỗi giờ mở cửa không theo quy chuẩn không làm sập parser."""
        weird_place = {
            "name": "Quán Trà Đá Vỉa Hè",
            "category": "CAFE",
            "working_hours": "tùy hứng, mưa thì nghỉ, nắng thì bán"
        }
        intervals = resolve_place_working_hours(weird_place)
        assert len(intervals) >= 1, "Must fall back to safe category default"
        assert intervals[0][0] < intervals[0][1]

    def test_nonexistent_prompt_keywords_handled_gracefully(self):
        """Từ khóa không có trong database trả về thông báo lỗi thân thiện, không văng 500."""
        res = generate_multi_day_plan(["khong_the_tim_thay_dia_diem_nay_99999"], days=1)
        assert "error" in res
        assert "Không tìm thấy" in res["error"]

    def test_coincident_duplicate_coordinates(self):
        """Hai địa điểm trùng tọa độ GPS 100% không gây lỗi chia cho 0."""
        p1 = {"name": "P1", "category": "ATTRACTION", "lat": 21.0285, "lng": 105.8542}
        p2 = {"name": "P2", "category": "ATTRACTION", "lat": 21.0285, "lng": 105.8542}
        sim, is_valid, d = simulate_route([p1, p2])
        assert is_valid is True
        assert d == 0.0
