# TRAVEL AI - PROJECT CONTEXT & ARCHITECTURE

## 1. Project Goal
Build a production-grade, AI-assisted domestic travel planning system ("VNTravel AI") for Vietnam's 34 provinces. The system takes natural language prompts and user constraints, queries real verified places from a local SQLite database, applies deterministic optimization algorithms (clustering, routing, hotel anchoring, budget calculation), and presents an actionable, human-like itinerary.

---

## 2. Core Philosophy: The AI Sandwich
1. **AI NLU Layer**: Extracts intent, target province, number of days, party size, transportation, and interest tags.
2. **Deterministic Engine**: 
   - Queries `travel_db.db`.
   - Clusters places by geographic density per day.
   - Generates shortest path within each day.
   - Slots places into human biological rhythm (Morning, Lunch, Midday Rest, Afternoon, Dinner, Night).
   - Evaluates inter-day hotel anchors and recommends switching if distance threshold $> 30-40\text{ km}$.
   - Aggregates true itemized costs.
3. **AI Explainer & NLG**: Explains why certain places or hotel switches were recommended, and enables conversational re-planning.

---

## 3. Tech Stack & Existing Codebase Structure
- **Backend**: Python 3.10+, FastAPI (`app/main.py`), SQLAlchemy 2.0 (`app/models.py`), Pydantic.
- **Database**: Thuần SQLite 100% (`travel_db.db`), triển khai zero-config, khởi động tức thì (loại bỏ hoàn toàn PostgreSQL & Docker). Lưu trữ:
  - `provinces`: 34 tỉnh/thành phố quy hoạch của dự án.
  - `wards`: 3.321 đơn vị hành chính xã/phường.
  - `places`: Danh thắng, chùa chiền, khách sạn, nhà hàng, chợ với tọa độ chuẩn (`lat`, `lng`), đánh giá, `price_range` và `prices` JSON.
- **Algorithms & Services**:
  - `app/services/travel_calculator.py`: Haversine distance, Nearest Neighbor TSP, vehicle transport rates, dynamic database price formatting.
  - `app/services/province_service.py`: Province querying.
- **API Routers**:
  - `app/routers/planner_router.py`: `POST /api/plan/calculate`.

### 3.1. NLU Parsing Contract & Origin vs Destination Disambiguation
Để triệt tiêu lỗi nhầm lẫn tai hại (như người dùng gõ *"Tới Quảng Nam đi máy bay xuất phát từ Bắc Ninh"* nhưng hệ thống lại xếp lịch trình *Bắc Ninh ➔ Bắc Ninh*):
1. **Ranh giới thực thể bắt buộc**:
   - `origin`: Tỉnh/Điểm xuất phát (Điểm đón đầu tiên & Điểm kết thúc).
   - `destination`: Tỉnh/Điểm đến thực sự nơi các hoạt động du lịch, khách sạn, ẩm thực diễn ra.
   - `prefer_flight`: `True` nếu người dùng yêu cầu đi máy bay hoặc khoảng cách liên tỉnh $\ge 300\text{km}$.
2. **Quy tắc điều hướng dữ liệu**:
   - Toàn bộ danh lam, nhà hàng, khách sạn truy vấn từ SQLite `travel_db.db` **BẮT BUỘC thuộc về `destination`**.
   - `origin` tuyệt đối không được đưa vào danh sách tham quan trong ngày, mà chỉ dùng để dựng chặng First-mile (xe đón từ Origin ra Sân bay cửa ngõ hoặc chạy cao tốc đến Destination).

---

## 4. Ground-Truth Data & Fallback Rules

### Categories in Database (`PlaceCategory`):
- `HISTORICAL_SITE`: Di tích lịch sử / Văn hóa.
- `SPECIALTY_FOOD` & `RESTAURANT` & `SEAFOOD_RESTAURANT`: Ẩm thực, nhà hàng.
- `TEMPLE`: Chùa, Đền, Miếu.
- `HOTEL`: Khách sạn, Resort, Homestay.
- `MARKET`: Chợ dân sinh, chợ đêm, trung tâm mua sắm.
- `ATTRACTION`: Danh thắng, điểm tham quan tổng hợp.

### Missing Data Fallbacks (Khi `typical_time_spent` là NULL):
- `TEMPLE` / `HISTORICAL_SITE`: 90 phút (1h 30m).
- `RESTAURANT` / `SEAFOOD_RESTAURANT`: 75 phút (1h 15m).
- `HOTEL` (Nghỉ trưa/Check-in): 105 phút (1h 45m).
- `MARKET`: 60 phút (1h 00m).
- `CAFE` / `ATTRACTION`: 45 - 60 phút.

### Price Range Ground Truth:
- **Hotels**: Pulled directly from `places.price_range` and `places.prices` (real multi-provider rates e.g., Agoda, Booking).
- **Restaurants**: Pulled from DB if available; fallback to standard regional estimate (~100,000 - 300,000 VND / person).
- **Temples & Public Markets**: Strictly **0 VND / Free Entry / Public**.

### Photo Ground Truth & Wikipedia Standard:
- **Danh lam thắng cảnh, Di tích, Chùa chiền, Đền miếu**: Bắt buộc lấy ảnh thực tế 100% từ **Wikipedia / Wikimedia Commons** (qua REST API hoặc Search API) hoặc Google Maps CDN độ nét cao. Tuyệt đối không dùng ảnh minh họa giả hoặc ảnh stock lặp lại.
- **Khách sạn, Chợ, Quán ăn**: Bắt buộc là ảnh chụp thực tế riêng biệt từ Google Places CDN / Playwright; nghiêm cấm sao chép nhân bản 1 link ảnh cho nhiều cơ sở khác nhau.

### Real Address Ground Truth (Địa chỉ thực tế — Cấm địa chỉ giả mạo):
- **100% địa chỉ trả về qua API phải là địa chỉ thực địa có thật**: Số nhà, tên đường, ngõ/ngách, thôn/xã/phường, quận/huyện, tỉnh/thành phố chuẩn Google Maps `formatted_address` hoặc cấu trúc phân cấp hành chính chuẩn quốc gia.
- ❌ **CẤM HOÀN TOÀN** địa chỉ placeholder tự chế: `"{name}, {province}, Việt Nam"`. Nếu địa điểm tự nhiên không có số nhà (thác, đèo, đỉnh núi), phải ghi đúng địa danh hành chính cấp thôn/xã/huyện (ví dụ: `Đèo Ô Quy Hồ, Xã Sơn Bình, Huyện Tam Đường, Lai Châu`).

### Google Maps Pin & URL Ground Truth (Quy tắc Ghim Vị Trí & Cấm Tạo Ảo Giác URL):
- **Mục đích của Icon Ghim (📍)**: Khi backend đẩy dữ liệu (ảnh, tên, giá, thời gian mở cửa, địa chỉ), icon ghim trên frontend sẽ cho phép người dùng mở đúng **Google Business Profile / Place Page** để xem lối vào thực tế, giờ mở cửa thời gian thực và dẫn đường navigation (tránh sai sót khi chỉ dựa vào tọa độ GPS thuần túy).
- ❌ **TUYỆT ĐỐI CẤM TỰ Ý TẠO URL TÌM KIẾM GIẢ**: Nghiêm cấm tự ghép chuỗi `https://www.google.com/maps/search/?api=1&query=...` khi không có `place_id` xác thực. Link tìm kiếm tự chế có thể dẫn sai vị trí hoặc nhảy sang địa điểm trùng tên ở tỉnh khác, gây hậu quả nghiêm trọng cho người dùng thực tế.
- ✅ **Chỉ chấp nhận URL chuẩn xác thực**:
  1. `url` trích xuất trực tiếp từ Google Maps Scraper / Places API đã được thẩm định.
  2. HOẶC URL gắn liền với Google Place ID xác thực: `https://www.google.com/maps/place/?q=place_id:{google_place_id}` (với `google_place_id` bắt đầu bằng `ChIJ...`).
  3. Nếu địa điểm chưa có Place ID hoặc URL xác thực $\rightarrow$ trường `google_maps_url` **BẮT BUỘC ĐỂ `NULL`**. Frontend sẽ không hiển thị ghim giả hoặc hiển thị trạng thái chưa liên kết. Không được gian dối tạo ảo giác dữ liệu!

---

## 5. Transportation Cost Model
- **Ô tô cá nhân (`car`)**: $\text{Cost} = (\text{Distance km} \times 1.800\text{đ}) + 30.000\text{đ (gửi xe)}$.
- **Thuê xe du lịch riêng (`van`)**: $\text{Cost} = 1.000.000\text{đ base} + (\text{Distance km} \times 2.500\text{đ})$ trọn gói cả xe (chia đều cho cả nhóm).
- **Taxi / GrabCar (`taxi`)**: $\text{Cost} = 12.000\text{đ} + (\text{Distance km} \times 14.000\text{đ})$.
- **Xe máy (`motorbike`)**: $\text{Cost} = (\text{Distance km} \times 600\text{đ}) + 10.000\text{đ (gửi xe)}$.


---

## 6. Hotel Anchor Optimization Logic (Single Source: `travel_params.py`)
For a multi-day trip with days $D_1, D_2, \dots, D_N$:
- Let $E_i$ be the final destination of Day $i$.
- Let $S_{i+1}$ be the first destination of Day $i+1$.
- Let $H_{current}$ be the currently selected/pinned hotel (`selected_hotel_id`).
- If one-way distance between hotel and day's cluster $\ge 35\text{ km}$ (`HOTEL_FAR_ONE_WAY_KM`):
  - Retain user's chosen hotel as hard anchor (Zero-forcing, respect customer choice).
  - Query alternative hotels in `travel_db.db` near $S_{i+1}$.
  - If a candidate $H_{candidate}$ saves $\ge 20\text{ km}$ (`HOTEL_MIN_SAVING_KM`), activate **Smart Hotel Advisory Card**:
    - **Phương án A (Khuyên dùng)**: Gợi ý đổi sang $H_{candidate}$ để tiết kiệm thời gian ngồi xe.
    - **Phương án B (Tôn trọng khách)**: Giữ nguyên $H_{current}$, đề xuất xuất phát sớm hơn.
    - Làm giàu văn phong tự nhiên qua **Claude 4.6 AI Advisor** (`app/services/llm_service.py`).

---

## 7. Geolocation, Geocoding & Google Places API Integration Strategy

### 7.1. Current User Location Detection (Hybrid Multi-Tiered)
To provide a seamless, 1-click experience across both mobile and desktop (including wired Ethernet PCs without hardware GPS chips), the frontend implements a 3-layer hybrid resolver:
1. **Tier 1 (HTML5 Browser GPS)**:
   - Requests `navigator.geolocation.getCurrentPosition` with `enableHighAccuracy: false`, `timeout: 3500ms`, `maximumAge: 60000ms`.
   - If resolved, coordinates are reverse-geocoded via BigDataCloud to obtain district/city names in Vietnamese.
2. **Tier 2 (Automatic IP Geolocation Fallback)**:
   - Triggered automatically on `POSITION_UNAVAILABLE` (error code 2), `TIMEOUT` (error code 3), `file:///` protocol blocks, or when hardware GPS is absent.
   - Queries `https://api.bigdatacloud.net/data/reverse-geocode-client?localityLanguage=vi` (CORS-friendly, zero-auth, unthrottled).
   - Resolves client public IP to city/locality (e.g. `Ngọc Hà, Hà Nội` or `Quận Ba Đình, Hà Nội`) and approximate coordinates.
   - Secondary IP fallback: `https://ipwho.is/`.
   - **Zero-error guarantee**: Never blocks the user with modal error dialogs.
3. **Tier 3 (Safe Default)**:
   - Falls back to `Hà Nội Central` (`21.0285, 105.8542`) if the network is completely offline.

### 7.2. Address Search & Origin Selection (Google Places vs Free Alternatives)
For the trip starting point input (`#start-location-input`), users require granular address selection (e.g. specific hotels, residential towers, airports, landmarks):

| Feature / Metric | Free Base (Current) | Google Places API (New) | Goong Maps API (VN Specialized) |
| :--- | :--- | :--- | :--- |
| **Autocomplete Input** | Plain text input | Real-time dropdown as user types | Real-time dropdown as user types |
| **Address Granularity** | Manual string | House number, alley, landmark level | House number, landmark level (VN) |
| **Accuracy in Vietnam** | Heuristic / City-level | **Highest (100%)** | Very High (Optimized for VN) |
| **Cost & Quota** | 100% Free | \$200/month free tier (~28k requests) | Free tier (~3,000 requests/day) |
| **Requirements** | None | Credit Card (Visa/Mastercard) + GCP | API Key registration |

### 7.3. Google Places API Architecture & Security Guidelines
When enabling Google Places API:
1. **Backend Proxy Pattern (Strict Security Rule)**:
   - **NEVER** expose `GOOGLE_MAPS_API_KEY` in client-side HTML/JS.
   - Client queries `GET /api/places/autocomplete?query=...` on the FastAPI backend.
   - Backend attaches the API key, queries `https://places.googleapis.com/v1/places:autocomplete`, and caches responses in memory (LRU Cache) for identical queries to minimize quota usage.
2. **Session Token Optimization**:
   - Utilize Google Autocomplete Session Tokens to group autocomplete keystrokes into a single billable session until the user selects a place.
3. **Database Enrichment Pipeline**:
   - Use Google Places Details API to populate and enrich the remaining 33 provinces in `travel_db.db`:
     - Real operating hours (`working_hours` JSON).
     - Place rating and total user ratings count.
     - Formatted address and verified coordinates (`lat`, `lng`).
     - Real place photos (CDN URLs).

---

## 8. Robustness & User-Centered Scheduling Governance

### 8.1. Graceful 4-Tier Fallback Strategy (Xử lý khi thiếu dữ liệu)
When user requests generic micro-services (cyber games, billiards, laundromats) absent from `travel_db.db` and unresolvable via Apify:
- **Tier 1 (DB & Apify Ground Truth)**: Primary resolution.
- **Tier 2 (Semantic Substitution)**: Suggest closest verified entertainment equivalent from `travel_db.db` (amusement centers, cinema, boardgame cafes).
- **Tier 3 (Commercial Hub Stop)**: Route user to the central town street/commercial boulevard where such micro-services naturally cluster.
- **Tier 4 (Flexible Free-form Slot + Radar Button)**: Preserve time slot as `[Hoạt động tự do]` and render a 1-click Google Maps radar button to scan live surrounding services. Zero hallucination permitted.

### 8.2. Distance Outlier & Smart Advisory (Cảnh báo Điểm quá xa)
When an auxiliary place is $\ge 15 - 20\text{ km}$ ($> 35 - 45\text{ mins}$) away from the day's main cluster:
- Trigger Smart Advisory Card with exact travel time and vehicle cost overhead.
- Provide Option A (Recommended): Switch to equivalent place within $< 3\text{ km}$.
- Provide Option B: Keep place and automatically reposition to the day's end or on the most convenient adjacent day route.

### 8.3. Hard Pinned Constraints & Anchor-Based Clustering (Ghim ngày cố định)
- User-specified day/session bindings are supreme invariants (Hard Constraints).
- The pinned place acts as an Anchor Centroid for Day $X$, dynamically attracting nearby attractions and repelling distant ones to preserve optimal daily routing.

---

## 9. Multi-Modal Flight Transit Architecture
- **Threshold**: Inter-provincial Haversine distance $D \ge 300\text{ km}$.
- **Gateway Airport Catchment ($R \le 150\text{ km}$)**: Uses normalized multi-criteria scoring between flight frequency and road transit distance to automatically bind non-airport tourist destinations (e.g. Hội An $\to$ DAD, Sa Pa $\to$ HAN).
- **3-Piece Routing**:
  - `first_mile`: Origin $\to$ Departure Airport (Road via Goong API).
  - `air_corridor`: Departure Airport $\to$ Arrival Airport (Geodesic purple dashed arc `#7C3AED`, no road API calls).
  - `last_mile`: Arrival Airport $\to$ Destination Hotel/Attraction (Road via Goong API).

---

## 10. Long-Distance Road Trip Fatigue & Topographic Speed Model
- **Safety Fatigue Caps**:
  - Mandatory 30-min pit-stop every $3 - 3.5\text{ hours}$ (or $160 - 200\text{ km}$).
  - Maximum $8\text{ hours}$ driving per day ($\le 450\text{ km}$).
  - Mandatory intermediate overnight staging city for trips $\ge 650 - 700\text{ km}$ (e.g., Hà Nội $\leftrightarrow$ Đà Nẵng stops at Đồng Hới or Vinh).
- **Topographic Terrain Winding & Speed Matrix**:
  - Flat / Expressway: $K_{\text{topo}} = 1.25, V_{\text{avg}} = 80\text{ km/h}$.
  - Coastal / Rolling hills: $K_{\text{topo}} = 1.35, V_{\text{avg}} = 60\text{ km/h}$.
  - Mountain / Highland passes (Tây Bắc, Tây Nguyên): $K_{\text{topo}} = 1.75, V_{\text{avg}} = 35\text{ km/h}$.

---

## 11. Multi-Tier AI Architecture (AI Sandwich Bottom Layer)
- **LÕI 1 (PRIMARY CLOUD LLM - ĐÃ TRIỂN KHAI)**: **Claude 4.6** (`claude-sonnet-4-6` qua VyceAI API tại `https://vyceai.com/v1/chat/completions`).
  - Đảm nhiệm: Tạo lời khuyên đánh đổi khách sạn (`explain_hotel_tradeoff`) và tư vấn an toàn đường dài (`explain_roadtrip_tradeoff`).
  - Cache: In-memory LRU `_LLM_CACHE`.
  - Hiệu năng: Kiểm soát bởi cờ `include_ai_explanation: bool = False` tại API `/api/plan/calculate` để bảo toàn benchmark $< 100\text{ms}$.
- **LÕI 2 (LOCAL DUAL-GGUF ENSEMBLE ENGINE - ĐÃ TẠO MÔ HÌNH VÀ SẴN SÀNG TÍCH HỢP)**: Chạy trên Ollama cục bộ (`localhost:11434`):
  - **LÕI 2A (Strict Contract NLU Parser)**: **`vn-travel-qwen-v2`** (`Qwen2.5-7B-Instruct-v2.Q4_K_M.gguf`, `temperature = 0.0`).
    - Huấn luyện trên tập đối kháng thuần 128 mẫu (`train_nlu_v2_pure.jsonl`).
    - Nhiệm vụ: Bóc tách cấu trúc khế ước NLU, đảo ngữ (Điểm đến trước Điểm xuất phát), phủ định (*"không đi máy bay"*), Reference Tokens (`CURRENT_LOCATION`), cam kết Zero Semantic Mutation.
  - **LÕI 2B (Travel Domain Reasoner & Advisory Explainer)**: **`vn-travel-qwen:7b`** (`Qwen2.5-7B-Instruct.Q4_K_M.gguf`, `temperature = 0.1`).
    - Nhiệm vụ: Thuyết minh lịch trình, đàm thoại du lịch tự nhiên, thẩm định ý kiến thứ hai (Second Opinion) khi V2 cần kiểm chứng.
  - **Cơ chế Phối hợp Song hành (Synergy & Orchestration)**:
    - *Cascade Mode*: V2 trích xuất cấu trúc dữ liệu $\to$ Nếu format lỗi hoặc V2 offline $\to$ V1 tiếp quản dự phòng.
    - *Consensus Mode*: Cả hai cùng bỏ phiếu intent và điểm đến/xuất phát. Nếu có sự lệch pha, quyền quyết định khế ước thuộc về V2 (dựa trên ma trận đối kháng TC01-TC10).
- **LÕI 3 (DETERMINISTIC FALLBACK - ĐÃ TRIỂN KHAI)**: Mẫu câu xác định không phụ thuộc AI khi offline hoàn toàn $\rightarrow$ **Zero-Crash Resiliency (Không bao giờ crash 500)**.
- **[KẾ HOẠCH - ROADMAP] NLU Intent Request Router**: Thay thế parsing keywords bằng mô hình NLU phân tách tự động `origin`, `destination`, `days`, `vehicle` từ văn bản tự do trước khi query database.
- **[KẾ HOẠCH - ROADMAP] Conversational Re-planner**: Chatbot đa lượt hỗ trợ sửa đổi lịch trình theo thời gian thực.

---

## 12. Operations Research Optimization & Real-World Export
- **Routing Engine (ĐÃ TRIỂN KHAI)**: 2-Opt local search refinement triệt tiêu crossing edges, cải thiện 21.9% - 38.2% quãng đường thừa.
- **Hard Time-Window Scheduling (ĐÃ TRIỂN KHAI)**: Đối chiếu giờ mở cửa `working_hours`, giờ đóng cửa, giờ nghỉ trưa từ `travel_db.db` và 3 nhịp sinh học du lịch Việt Nam.
  - Ràng buộc: $\text{Arrival}_i + \text{Dwell}_i + \text{TravelTime}_{i \to j} \le \text{CloseTime}_j$.
  - Khi xung đột: Điều chỉnh lịch trình theo cửa sổ thời gian khả thi gần nhất, gắn cờ cảnh báo trên giao diện.
- **Bản đồ Goong Real Polylines (ĐÃ TRIỂN KHAI)**: Tích hợp Goong Directions API (`/api/map/directions`) với bộ đệm kép RAM + MD5 Disk Cache, Leaflet vẽ đường uốn lượn thực tế theo mạng lưới giao thông.
- **1-Click Hand-off (KẾ HOẠCH - ROADMAP P2)**:
  - Google Maps multi-waypoint direct navigation deep links.
  - iCal (`.ics`) file export with 15-minute advance reminder notifications.

---

## 13. Two-Speed Place Resolution & Province Terrain Coding

### 13.1. Two-Speed Apify Resolution (for places absent from DB)
| Lane | Method | Latency | Output |
|:---|:---|:---:|:---|
| **Lane A (Fast)** | Goong Geocoding API | < 300ms | `(lat, lng)` + raw address. Immediate UI render with `[Chưa xác minh]` badge. |
| **Lane B (Background)** | Apify `google-maps-scraper` | 10-30s | Full enrichment: `working_hours`, `rating`, `photo_url`, `google_place_id`. Auto-updates UI via polling or SSE. |

- Cache key for Apify results: `apify:{slugify(place_name)}:{province_code}` — TTL 7 days.
- If Lane B returns empty after 2 retries → discard Lane A result, activate 4-Tier Fallback (Section 8.1).
- Implementation module: `app/services/apify_fallback.py` (planned).

### 13.2. Province Terrain Mapping (`PROVINCE_TERRAIN` dict in `travel_calculator.py`)
```python
PROVINCE_TERRAIN = {
    # Đồng bằng / Cao tốc — K_topo=1.22, V_avg=80km/h
    "flat": ["ha_noi", "tp_ho_chi_minh", "hai_phong", "can_tho", "da_nang",
             "nam_dinh", "hung_yen", "thai_binh", "vinh_long", "dong_thap",
             "an_giang", "tien_giang", "long_an", "kien_giang"],
    # Bán sơn địa / Duyên hải — K_topo=1.35, V_avg=60km/h
    "coastal": ["thanh_hoa", "nghe_an", "ha_tinh", "quang_binh", "quang_tri",
                "thua_thien_hue", "quang_nam", "quang_ngai", "binh_dinh",
                "phu_yen", "khanh_hoa", "ninh_thuan", "binh_thuan", "quang_ninh",
                "binh_duong", "dong_nai", "ba_ria_vung_tau"],
    # Đèo dốc / Vùng cao — K_topo=1.75, V_avg=35km/h
    "highland": ["lao_cai", "yen_bai", "son_la", "dien_bien", "lai_chau",
                 "ha_giang", "cao_bang", "bac_kan", "tuyen_quang",
                 "kon_tum", "gia_lai", "dak_lak", "dak_nong", "lam_dong"],
}
K_TOPO = {"flat": 1.22, "coastal": 1.35, "highland": 1.75}
V_AVG  = {"flat": 80,   "coastal": 60,   "highland": 35}   # km/h
```
**Cross-terrain trips**: When origin and destination span different terrain groups, compute weighted-average $K_{\text{topo}}$ proportional to estimated distance through each zone (60% first zone + 40% second zone as safe default when exact split is unknown).

