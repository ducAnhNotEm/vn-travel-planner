# Actionable Tasks: 001-multi-day-planner-goong
<!-- Spec Kit Execution Tasks Checklist -->

## Phase 1: Goong Map Service & Backend Proxy
- [x] **Task 1.1**: Tạo `app/services/map_service.py` thực hiện gọi Goong Static Map Route API và lưu cache tại `data/map_cache/`.
- [x] **Task 1.2**: Tạo `app/routers/map_router.py` với endpoint `GET /api/map/static-route` và đăng ký vào `app/main.py`.

## Phase 2: Core Planning Engine (Multi-day, Rhythm & Costs)
- [x] **Task 2.1**: Cập nhật `calculate_transport_cost` trong `app/services/travel_calculator.py` hỗ trợ `group_size` (tính tiền cả đoàn và chia bình quân đầu người).
- [x] **Task 2.2**: Cài đặt thuật toán phân cụm địa lý đa ngày thuần Python `cluster_places_by_days`.
- [x] **Task 2.3**: Cài đặt bộ sắp xếp nhịp sinh học `sequence_by_human_rhythm` và điền khuyết `fill_gaps_from_db`.
- [x] **Task 2.4**: Cài đặt hàm `generate_multi_day_plan` tổng hợp lịch trình $K$ ngày, kết nối Goong static map URL và tính toán chi phí cả đoàn & mỗi người.

## Phase 3: Router & API Updates
- [x] **Task 3.1**: Cập nhật `app/routers/planner_router.py` hỗ trợ tham số `days` và `group_size` trong `TripPlanRequest`.

## Phase 4: Frontend UI Enhancement
- [x] **Task 4.1**: Cập nhật `frontend/index.html` thêm input chọn số ngày và số người trong đoàn.
- [x] **Task 4.2**: Nâng cấp giao diện hiển thị Timeline đa ngày với Tabs, khung ảnh Goong Static Map, và thẻ tóm tắt chi phí cả đoàn vs từng người.

## Phase 5: Verification & Convergence
- [x] **Task 5.1**: Chạy kiểm thử tự động với dữ liệu thực tế từ `travel_db.db` (Tour 3 ngày Đà Nẵng, 4 người đi ô tô).
- [x] **Task 5.2**: Cập nhật trạng thái trong `IMPLEMENTATION_STATUS.md` và kiểm tra `git status`.
