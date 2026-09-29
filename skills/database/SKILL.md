# Database & Place Ingestion Skill

## Purpose
Ensure ground truth data integrity in SQLite `travel_db.db`, enforce schema compliance, and manage place querying and ingestion.

## Database Location & Engine
- SQLite Path: `d:\vn-travel-planner\travel_db.db`
- Engine: Pure Standalone SQLite 100% (SQLAlchemy `SessionLocal` from `app.database` or raw Python `sqlite3.connect()`).
- Note: Loại bỏ hoàn toàn PostgreSQL và Docker để đạt hiệu năng khởi động tức thì (0ms) và triển khai zero-config.

## Core Tables & Fields
1. `provinces`: `code` (PK), `name`, `codename`, `city_name`, `division_type`, `is_in_project`, `province_type`, `has_sea`, `scrape_limit`.
2. `wards`: `code` (PK), `province_code` (FK), `name`, `codename`, `division_type`.
3. `places`:
   - `id` (PK, Integer)
   - `google_place_id` (String, Unique)
   - `province_code` (Integer, FK)
   - `name` (String, Non-null)
   - `category` (Enum `PlaceCategory`: `HISTORICAL_SITE`, `SPECIALTY_FOOD`, `RESTAURANT`, `SEAFOOD_RESTAURANT`, `TEMPLE`, `HOTEL`, `MARKET`, `ATTRACTION`)
   - `is_must_visit` (Boolean)
   - `badge_label` (String, Nullable)
   - `lat` (Float, Non-null), `lng` (Float, Non-null)
   - `address` (String)
   - `rating` (Float), `review_count` (Integer)
   - `image_url` (Text)
   - `typical_time_spent` (String, Nullable)
   - `popular_times` (JSON, Nullable)
   - `price_range` (String, Nullable) - e.g., "$67 - $95"
   - `prices` (JSON, Nullable) - Array of provider rates
   - `tags` (JSON, Nullable)

## Ingestion Protocol for New Provinces
When adding 10-20 places per category from Google Places API:
1. Deduplicate by `google_place_id`.
2. Map Google types:
   - `restaurant`, `food` $\rightarrow$ `RESTAURANT`
   - `lodging`, `hotel` $\rightarrow$ `HOTEL`
   - `place_of_worship`, `hindu_temple`, `church` $\rightarrow$ `TEMPLE`
   - `market`, `shopping_mall` $\rightarrow$ `MARKET`
3. Parse `prices` array if available; compute human-readable `price_range`.
4. Ensure valid `lat` and `lng` floats; never insert null coordinates.
5. **Photo Ground Truth**:
   - Đối với danh lam thắng cảnh, chùa, đền, di tích lịch sử: Bắt buộc truy vấn ảnh thực tế 100% từ **Wikipedia / Wikimedia Commons** (dùng `scripts/test_wiki_photos.py` hoặc Wikipedia API). Tuyệt đối không dùng ảnh minh họa giả.
   - Đối với khách sạn, chợ, nhà hàng: Nếu chưa có ảnh xác thực riêng thì để `null`, nghiêm cấm tái sử dụng trùng lặp link ảnh.
