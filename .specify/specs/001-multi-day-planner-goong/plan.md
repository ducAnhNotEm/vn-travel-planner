# Technical Plan: 001-multi-day-planner-goong
<!-- Spec Kit Technical Plan -->

## 1. Architecture Overview

```
[FRONTEND UI] 
   │  - Nhập: province_id, keywords, days, group_size, vehicle
   │  - Hiển thị: Timeline Tabs (Ngày 1, 2, 3), Ảnh Goong Map tĩnh, Bảng chi phí đoàn/người
   ▼
[API ROUTER: /api/plan/calculate & /api/map/static-route]
   │
   ├──► [MAP SERVICE: app/services/map_service.py]
   │       - Đọc GOONG_API_KEY từ .env
   │       - Quản lý cache ảnh tại data/map_cache/
   │       - Gọi Goong Static Map Route API (https://rsapi.goong.io/staticmap/route)
   │
   └──► [CORE ENGINE: app/services/travel_calculator.py]
           - Multi-day clustering (Haversine distance-based K-Means)
           - Biological Rhythm slot assignment (Sáng -> Trưa -> Chiều -> Tối)
           - Auto gap-filling từ travel_db.db
           - Hotel switching alert (ngưỡng >= 35km)
           - Group expense & per-person allocation
```

## 2. Component Design & Changes

### 2.1. Core Engine (`app/services/travel_calculator.py`)
- Thêm hàm `cluster_places_by_days(places, days) -> List[List[Dict]]`:
  - Dùng thuật toán K-Medoids / Distance-based density thuần Python (không cần thêm dependency ngoài).
- Thêm hàm `sequence_by_human_rhythm(day_places) -> List[Dict]`:
  - Phân loại theo category: `ATTRACTION` (sáng), `RESTAURANT` (trưa/tối), `ACTIVITY` (chiều), `MARKET` (tối/đêm).
- Thêm hàm `fill_gaps_from_db(province_id, current_places, needed_slots, db_path) -> List[Dict]`:
  - Lấy thêm nhà hàng, quán cafe hoặc danh thắng lân cận trong cùng tỉnh.
- Nâng cấp `calculate_transport_cost(distance_km, vehicle_type, group_size)`:
  - Tính tổng chi phí cho cả đoàn.
  - Tính chi phí bình quân trên mỗi người (`cost_per_person = total / group_size`).
  - Xử lý sức chứa: xe máy $\lceil group\_size / 2 \rceil$ xe, ô tô/taxi theo quy mô đoàn.
- Nâng cấp `generate_multi_day_plan(...)`:
  - Điều phối toàn bộ luồng xử lý đa ngày và trả về cấu trúc JSON hoàn chỉnh.

### 2.2. Map Service & Router (`app/services/map_service.py` & `app/routers/map_router.py`)
- Service `get_static_route_map(origin_lat, origin_lng, dest_lat, dest_lng, vehicle)`:
  - Hash URL request thành `cache_key`.
  - Nếu file ảnh `.png` đã tồn tại trong `data/map_cache/` $\rightarrow$ đọc và trả về ngay.
  - Nếu chưa có $\rightarrow$ gọi `https://rsapi.goong.io/staticmap/route` với `GOONG_API_KEY`, lưu vào disk rồi trả về `Response(content=..., media_type="image/png")`.
- Router `GET /api/map/static-route` phục vụ trực tiếp cho thẻ `<img>` trên Frontend.

### 2.3. Frontend Integration (`frontend/index.html`)
- Bổ sung bộ điều khiển chọn `Số ngày` (1 - 5 ngày) và `Số người` (1 - 10 người).
- Nâng cấp phần hiển thị Lịch trình:
  - Tabs chuyển đổi giữa các ngày (`Ngày 1`, `Ngày 2`, `Ngày 3`).
  - Khung ảnh Goong Static Map lộ trình của từng ngày.
  - Các mốc thời gian rõ ràng: `🌅 Sáng 08:30`, `🍲 Trưa 12:00`, `☕ Chiều 14:30`, `🌙 Tối 18:30`.
  - Thẻ tóm tắt tài chính 2 cột: `Tổng chi phí cả đoàn` vs `Chi phí dự kiến mỗi người`.

## 3. Security & Safety Guards
- `GOONG_API_KEY` chỉ đọc trong `map_service.py` từ `.env`.
- Bọc `try/except` cho request Goong Map: nếu timeout hoặc lỗi, trả về placeholder hoặc ẩn khung map để không ảnh hưởng đến trải nghiệm người dùng.
