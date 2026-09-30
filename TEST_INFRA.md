# HẠ TẦNG & TÀI LIỆU KIỂM THỬ TỰ ĐỘNG (TEST INFRASTRUCTURE)
## Hệ thống Hành trình Hàng không Khép kín (Door-to-Door Flight Transit Pipeline)

> **Dự án**: VNTravel AI (`vn-travel-planner`)  
> **Tác giả**: Test Writer (E2E Verification Specialist)  
> **Tiêu chuẩn Kỹ thuật**: Top 0.1% Elite Engineering Standard & `AGENTS.md`  
> **Nguyên tắc Cốt lõi**: Không gian dối (Zero Mock/Cheat), 100% dữ liệu thực địa từ `travel_db.db`, phòng thủ Zero-Failure Resiliency.

---

## 1. Tổng quan Kiến trúc Kiểm thử (Test Architecture)

Hạ tầng kiểm thử được thiết kế dựa trên triết lý **Deterministic Mathematical Rigor & Defensive Verification**, bảo đảm mọi tính toán điều phối hàng không và định tuyến đường bộ đều được thẩm tra trực tiếp trên cơ sở dữ liệu thật `travel_db.db`.

```
                                  KIẾN TRÚC HẠ TẦNG KIỂM THỬ
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │                          TEST RUNNER (pytest 9.1.1 + Python 3.12)                      │
 └──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                            │
               ┌────────────────────────────┼────────────────────────────┐
               ▼                            ▼                            ▼
 ┌──────────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────────┐
 │    1. Ground Truth DB    │ │ 2. Thuật toán Cửa ngõ    │ │  3. Phòng thủ Zero-Fail   │
 │   - 22 sân bay dân sự    │ │   - Haversine Nearest    │ │   - Key rác / Hết quota   │
 │   - Schema & IATA code   │ │   - Gateway Catchment    │ │   - Network Timeout       │
 │   - Place ID & Tọa độ    │ │   - Ngưỡng D >= 300km    │ │   - Fallback Geodesic     │
 └──────────────────────────┘ └──────────────────────────┘ └──────────────────────────┘
               │                            │                            │
               └────────────────────────────┼────────────────────────────┘
                                            │
               ┌────────────────────────────┴────────────────────────────┐
               ▼                                                         ▼
 ┌──────────────────────────┐                               ┌──────────────────────────┐
 │ 4. Performance & Cache   │                               │ 5. End-to-End API (E2E)  │
 │   - Độ trễ RAM < 1.5s    │                               │   - Plan Enrichment      │
 │   - LRU Eviction & Safety│                               │   - 3 Chặng + Thẻ Timeline│
 └──────────────────────────┘                               │   - FastAPI TestClient   │
                                                            └──────────────────────────┘
```

---

## 2. Bố cục Mã nguồn & Tệp sở hữu (Test Layout)

```
D:\vn-travel-planner\
├── tests\
│   ├── __init__.py                 # Khởi tạo package tests
│   └── test_flight_transit.py      # Bộ kiểm thử tự động toàn diện (38 test cases)
├── TEST_INFRA.md                   # Tài liệu đặc tả hạ tầng kiểm thử (tệp này)
├── travel_db.db                    # Cơ sở dữ liệu SQLite thực địa (1.92 MB, 22 sân bay)
└── .agents\teamwork\test_writer_1\ # Thư mục siêu dữ liệu agent kiểm thử
    ├── DISPATCH.md                 # Nhật ký nhiệm vụ
    ├── BRIEFING.md                 # Tình huống tác nghiệp
    ├── progress.md                 # Tiến độ thực hiện
    └── handoff.md                  # Báo cáo bàn giao 5 thành phần chuẩn hóa
```

---

## 3. Ma trận Kiểm thử Chi tiết (Verification Test Matrix)

Bộ kiểm thử được tổ chức thành **7 nhóm chuyên biệt (Test Suites)** bao phủ 100% các tiêu chí chấp thuận (Acceptance Criteria):

| # | Nhóm Kiểm thử (Suite) | Số Test Cases | Mục tiêu Kiểm chứng | Kết quả |
|---|---|:---:|---|:---:|
| 1 | `TestGroundTruthAirports` | 7 | Xác minh cơ sở dữ liệu thật `travel_db.db`: đủ 22 sân bay, 11 quốc tế, 11 nội địa, tọa độ trong biên giới VN, địa chỉ bưu chính và Google Place ID xác thực. | **PASSED** (7/7) |
| 2 | `TestNearestAirportDiscovery` | 6 | Thuật toán Haversine phát hiện chính xác sân bay xuất phát: Hà Nội -> HAN, TP.HCM -> SGN, Đà Nẵng -> DAD, Hải Phòng -> HPH, Cần Thơ -> VCA. | **PASSED** (6/6) |
| 3 | `TestGatewayCatchmentArea` | 7 | Quét sân bay cửa ngõ cho tỉnh không có sân bay riêng: Hội An -> DAD, Mũi Né -> CXR, Sa Pa -> HAN, Ninh Bình -> HAN, Vũng Tàu -> SGN, chấm điểm bán kính 150km. | **PASSED** (7/7) |
| 4 | `TestDistanceThreshold` | 4 | Ngưỡng phân luồng cự ly: $D < 300\text{ km}$ (Hà Nội - Ninh Bình 86.7 km) giữ đường bộ; $D \ge 300\text{ km}$ (Hà Nội - Đà Nẵng 606.3 km) kích hoạt bay; hỗ trợ cưỡng bức `prefer_flight`. | **PASSED** (4/4) |
| 5 | `TestDefensiveResiliency` | 7 | Phòng thủ Zero-Failure: Key Goong sai, lỗi 403, timeout -> tự động fallback về đường thẳng Geodesic 2 điểm (mã 200), giải mã Google Polyline, tạo đường cong Bézier. | **PASSED** (7/7) |
| 6 | `TestPerformanceAndCache` | 3 | Hiệu năng xử lý: Truy vấn trong bộ đệm LRU phản hồi cực nhanh (< 1.5 giây, thực tế < 1ms), kiểm thử an toàn đa luồng (Thread-safe) và cơ chế dọn bộ nhớ LRU. | **PASSED** (3/3) |
| 7 | `TestEndToEndIntegration` | 4 | Tích hợp đầu cuối: Làm giàu lịch trình 3 chặng, 5 thẻ Timeline sinh học Ngày 1 & Ngày về, tổng chi phí đoàn, backward compatibility cự ly ngắn & FastAPI TestClient. | **37 PASSED / 1 XFAIL** |

---

## 4. Hướng dẫn Thực thi Kiểm thử (How to Run Tests)

### 4.1. Lệnh Chạy Toàn Bộ Bộ Kiểm Thử
Chạy với môi trường ảo Python của dự án:
```powershell
.\venv\Scripts\pytest tests/test_flight_transit.py -v
```

Hoặc chạy trực tiếp với Python hệ thống:
```powershell
pytest tests/test_flight_transit.py -v
```

### 4.2. Chạy Theo Từng Nhóm Chuyên Biệt
- **Kiểm tra dữ liệu thực địa 22 sân bay**:
  ```powershell
  pytest tests/test_flight_transit.py -k "TestGroundTruthAirports" -v
  ```
- **Kiểm tra phát hiện sân bay xuất phát & cửa ngõ**:
  ```powershell
  pytest tests/test_flight_transit.py -k "Nearest or Gateway" -v
  ```
- **Kiểm tra cơ chế phòng thủ Goong API & Geodesic Fallback**:
  ```powershell
  pytest tests/test_flight_transit.py -k "TestDefensiveResiliency" -v
  ```
- **Kiểm tra tích hợp đầu cuối & làm giàu lịch trình**:
  ```powershell
  pytest tests/test_flight_transit.py -k "TestEndToEndIntegration" -v
  ```

---

## 5. Báo cáo Chi tiết & Trạng thái Milestone Tracing

### 5.1. Kết quả Kiểm định Hiện tại
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1
collected 38 items

tests/test_flight_transit.py::TestGroundTruthAirports::test_database_file_exists_and_accessible PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_airports_table_exact_22_count PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_airports_iata_codes_uniqueness_and_format PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_airports_geographic_coordinates_in_vietnam_bounds PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_airports_international_and_domestic_distribution PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_airports_addresses_and_google_place_ids PASSED
tests/test_flight_transit.py::TestGroundTruthAirports::test_service_get_all_airports_returns_pydantic_models PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_hanoi_center_discovers_noi_bai PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_hcmc_district_1_discovers_tan_son_nhat PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_danang_city_discovers_dad PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_haiphong_discovers_cat_bi PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_cantho_discovers_vca PASSED
tests/test_flight_transit.py::TestNearestAirportDiscovery::test_exact_proximity_terminal_runway PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_hoi_an_destination_pairs_with_dad PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_mui_ne_destination_pairs_with_cxr PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_sapa_destination_pairs_with_han PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_ninh_binh_destination_pairs_with_han PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_vung_tau_destination_pairs_with_sgn PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_direct_airport_cities_pair_with_own_airport PASSED
tests/test_flight_transit.py::TestGatewayCatchmentArea::test_catchment_scoring_prefers_international_hub PASSED
tests/test_flight_transit.py::TestDistanceThreshold::test_hanoi_to_ninh_binh_short_distance_keeps_road_routing PASSED
tests/test_flight_transit.py::TestDistanceThreshold::test_hanoi_to_danang_long_distance_triggers_flight_pipeline PASSED
tests/test_flight_transit.py::TestDistanceThreshold::test_hanoi_to_hcmc_long_distance_triggers_flight_pipeline PASSED
tests/test_flight_transit.py::TestDistanceThreshold::test_short_distance_with_prefer_flight_override PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_invalid_goong_key_returns_geodesic_fallback PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_network_timeout_triggers_geodesic_fallback PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_http_403_or_500_triggers_geodesic_fallback PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_decode_polyline_google_encoded_standard_vector PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_decode_polyline_empty_and_corrupt_strings PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_flight_arc_bezier_geometry PASSED
tests/test_flight_transit.py::TestDefensiveResiliency::test_flight_arc_degenerate_identical_coordinates PASSED
tests/test_flight_transit.py::TestPerformanceAndCache::test_cached_requests_execute_under_1_5_seconds PASSED
tests/test_flight_transit.py::TestPerformanceAndCache::test_lru_cache_capacity_eviction_and_lru_order PASSED
tests/test_flight_transit.py::TestPerformanceAndCache::test_lru_cache_thread_safety_under_concurrent_load PASSED
tests/test_flight_transit.py::TestEndToEndIntegration::test_plan_enrichment_with_real_multi_day_plan PASSED
tests/test_flight_transit.py::TestEndToEndIntegration::test_plan_enrichment_backward_compatibility_for_short_trips PASSED
tests/test_flight_transit.py::TestEndToEndIntegration::test_fastapi_plan_calculate_endpoint_with_flight XFAIL
tests/test_flight_transit.py::TestEndToEndIntegration::test_fastapi_plan_calculate_legacy_request_backward_compatibility PASSED

======================== 37 passed, 1 xfailed in 6.10s ========================
```

### 5.2. Giải trình Trạng thái XFAIL & Báo cáo Bàn giao
- **37 Test Cases Đạt 100% (PASSED)**:
  - Toàn bộ cơ sở dữ liệu `travel_db.db` và các giải thuật cốt lõi trong `app/services/flight_transit_service.py` hoạt động hoàn hảo, chuẩn xác, không có lỗi ngoại lệ.
  - Hàm `enrich_plan_with_flight_transit` tích hợp thành công trên các lịch trình đa ngày thực tế sinh từ `travel_calculator.py`.
- **1 Test Case Đánh dấu XFAIL (`test_fastapi_plan_calculate_endpoint_with_flight`)**:
  - **Lý do**: Milestone 2 (Router Integration trong `app/routers/planner_router.py`) là phụ thuộc tiếp theo chưa được triển khai.
  - Khi Milestone 2 được hoàn tất (bổ sung các trường `origin_lat`, `origin_lng`, `prefer_flight` vào `TripPlanRequest` và gọi `enrich_plan_with_flight_transit`), test case này sẽ tự động chuyển từ `XFAIL` sang `PASSED` mà không cần sửa bất kỳ dòng mã kiểm thử nào.
