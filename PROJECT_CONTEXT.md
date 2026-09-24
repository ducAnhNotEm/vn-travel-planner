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
- **Database**: SQLite (`travel_db.db`) storing:
  - `provinces`: 34 planned provinces/cities.
  - `wards`: Administrative subdivisions.
  - `places`: Attractions, temples, hotels, restaurants, cafes, markets with coordinates (`lat`, `lng`), ratings, review counts, Google Place IDs, `price_range`, and `prices` JSON.
- **Algorithms & Services**:
  - `app/services/travel_calculator.py`: Haversine distance, Nearest Neighbor TSP, vehicle transport rates, dynamic database price formatting.
  - `app/services/province_service.py`: Province querying.
- **API Routers**:
  - `app/routers/planner_router.py`: `POST /api/plan/calculate`.

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

---

## 5. Transportation Cost Model
- **Ô tô cá nhân (`car`)**: $\text{Cost} = (\text{Distance km} \times 1.800\text{đ}) + 30.000\text{đ (gửi xe)}$.
- **Thuê xe du lịch riêng (`chartered_van`)**: $\text{Cost} = 1.000.000\text{đ base} + (\text{Distance km} \times 2.500\text{đ})$ trọn gói cả xe (chia đều cho cả nhóm).
- **Taxi / GrabCar (`taxi`)**: $\text{Cost} = 12.000\text{đ} + (\text{Distance km} \times 14.000\text{đ})$.
- **Xe máy (`motorbike`)**: $\text{Cost} = (\text{Distance km} \times 600\text{đ}) + 10.000\text{đ (gửi xe)}$.


---

## 6. Hotel Anchor Optimization Logic
For a multi-day trip with days $D_1, D_2, \dots, D_N$:
- Let $E_i$ be the final destination of Day $i$.
- Let $S_{i+1}$ be the first destination of Day $i+1$.
- Let $H_{current}$ be the currently selected hotel.
- If $\text{dist}(E_i, H_{current}) + \text{dist}(H_{current}, S_{i+1}) \ge 40\text{ km}$:
  - Query all hotels in DB near $S_{i+1}$.
  - Find $H_{candidate}$ that minimizes travel distance.
  - If distance saved $\ge 25\text{ km}$ and time saved $\ge 45\text{ mins}$, trigger **Switch Hotel Recommendation Alert**.

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

