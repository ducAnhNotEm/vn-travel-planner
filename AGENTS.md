# TRAVEL AI - PROJECT RULES & AGENT GOVERNANCE

## 0. Coding Philosophy — Lazy Senior Dev (Ponytail)

> **"The best code is the code never written."**  
> Inspired by [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) — adapted for this project.

Before writing **any** code, stop at the first rung of this ladder that holds:

```
1. Does this need to exist at all?          → No: skip it, say so. (YAGNI)
2. Already in this codebase?               → Reuse — check app/services/ first.
3. Standard library / Python built-in?     → Use it.
4. Already-installed dependency?           → Use it. Never add a new dep for what
                                             a few lines can do.
5. Can it be one line?                     → One line.
6. Only then: write the minimum that works.
```

**The ladder runs AFTER understanding the problem**, not instead of it.  
Read the task, trace the real code flow end-to-end, then climb.

### 🔒 Safety Override — These rules ALWAYS win over the ladder:
- Validation, error handling, data-loss guards → **NEVER cut**
- Haversine / distance calculations → **ALWAYS use deterministic engine** (not mental math)
- Ground truth from `travel_db.db` → **NEVER invent or guess**
- API key security (backend-only) → **NEVER expose to frontend**

*Deletion over addition. Boring over clever. Fewest files possible.*  
*But: the smallest change in the wrong place is a second bug, not a fix.*

---

## 1. Mandatory Workflow for Coding Agents

Before modifying or creating any code, the AI Agent MUST strictly execute this pipeline:

```
TASK ASSIGNED
      │
      ▼
1. READ AGENTS.md & PROJECT_CONTEXT.md
      │
      ▼
2. INSPECT CURRENT IMPLEMENTATION
   (Check app/models.py, app/services/, app/routers/, travel_db.db)
      │
      ▼
3. CHECK EXISTING CAPABILITIES & PREVENT DUPLICATION
   (Never create duplicate files like hotelOptimizer.py if travel_calculator.py exists)
      │
      ▼
4. IMPACT ANALYSIS & STEP-BY-STEP PLAN
      │
      ▼
5. IMPLEMENT CODE (Preserve existing working functions)
      │
      ▼
6. EXECUTE TESTS ON REAL DATABASE (travel_db.db)
      │
      ▼
7. UPDATE IMPLEMENTATION_STATUS.md & REPORT
```

---

## 2. Architectural Boundaries & "Iron Laws"

### The Golden Rule: AI Sandwich Pattern
- **Top Layer (LLM Parser - NLU)**: Understand user intent, extract constraints (province, days, group size, vehicle, preferences).
- **Middle Layer (Deterministic Python Core Engine)**: Handles ALL calculations, routing, clustering, hotel distance evaluation, and financial sums.
- **Bottom Layer (LLM Explainer - NLG)**: Translates algorithmic decisions into friendly, contextual explanations (e.g., explaining why a hotel switch was recommended).

### Strict Negative Constraints:
- ❌ **LLM MUST NOT** directly calculate route distances or travel times in its head. (Must execute Haversine or matrix API).
- ❌ **LLM MUST NOT** decide hotel switching on pure intuition. (Must strictly follow distance threshold & cost evaluation).
- ❌ **LLM MUST NOT** calculate bill totals or split expenses mentally. (Must use deterministic math).
- ❌ **LLM MUST NOT** guess or invent coordinates, opening hours, or room prices. Ground truth must come from `travel_db.db`.
- ❌ **NEVER EXPOSE PAID API KEYS (Google Maps / Goong Maps)** in public frontend code. All third-party geocoding / autocomplete API calls with paid keys MUST route through a backend endpoint (`/api/...`) with in-memory caching to prevent quota exhaustion and credential leakage.
- ❌ **NEVER BREAK ZERO-ERROR GEOLOCATION**: Free client fallbacks (HTML5 Geolocation + IP reverse-geocoding via BigDataCloud/IPWhois) must always remain operational even if external Google API keys are missing or quota is exceeded.

---

## 3. Data Integrity & Pacing Rules

- **No Hallucinated Places**: Every location in an itinerary MUST exist in `travel_db.db`.
- **Real Address Ground Truth (Địa chỉ thực tế 100% — Cấm địa chỉ giả mạo)**:
  - ❌ **TUYỆT ĐỐI CẤM ĐỊA CHỈ PLACEHOLDER**: Nghiêm cấm tạo hoặc trả về địa chỉ tự chế dạng `"{name}, {province}, Việt Nam"`.
  - Mọi địa chỉ trả về qua API phải là **địa chỉ bưu chính/thực địa có thật 100%** (số nhà, tên đường/phố, thôn/ấp, xã/phường, quận/huyện, tỉnh/thành phố) được lấy từ Google Maps `formatted_address` hoặc cấu trúc hành chính thực tế.
  - Đối với danh thắng tự nhiên xa khu dân cư (thác nước, đỉnh núi), địa chỉ phải ghi rõ thôn/xã/huyện thực tế (ví dụ: `Xã Tam Thanh, Huyện Quan Sơn, Thanh Hóa`), tuyệt đối không bịa đặt số nhà hay tên đường không có thật.
- **Zero URL Fabrication & Anti-Hallucination (Tuyệt đối không chế URL — Cấm tạo ảo giác)**:
  - ❌ **NGHIÊM CẤM TỰ Ý TẠO URL TÌM KIẾM GIẢ**: Không được tự sinh URL tìm kiếm chung chung như `https://www.google.com/maps/search/?api=1&query=...` để tạo ảo giác là địa điểm nào cũng có link. Việc này cực kỳ nguy hiểm vì query text có thể dẫn người dùng đến sai địa điểm, sai cổng vào, hoặc một quán trùng tên ở tỉnh khác.
  - ✅ **QUY CHUẨN URL THẬT (Ground-Truth Only)**:
    - `google_maps_url` **CHỈ ĐƯỢC PHÉP CÓ GIÁ TRỊ** khi:
      1. Trích xuất trực tiếp từ trường `url` của Google Maps Scraper có kiểm định, HOẶC
      2. Gắn liền với Google Place ID xác thực chuẩn Google (`https://www.google.com/maps/place/?q=place_id:{google_place_id}` với `google_place_id` bắt đầu bằng `ChIJ...`).
    - Nếu một địa điểm **CHƯA CÓ Place ID hoặc URL xác thực**, trường `google_maps_url` **BẮT BUỘC ĐỂ `NULL`**. Thà để `NULL` để frontend ẩn nút ghim, còn hơn vẽ ra link giả làm người dùng đi lạc đường.
- **Photo Authenticity & Ground Truth (Chân thật 100% về hình ảnh)**:
  - ❌ **TUYỆT ĐỐI KHÔNG DÙNG ẢNH GIẢ HOẶC COPY LINK STOCK MINH HỌA LẶP LẠI**: Mọi địa điểm danh thắng, chùa chiền, đền miếu, di tích lịch sử khi đưa vào database hoặc lịch trình **bắt buộc phải lấy ảnh chụp thực tế 100% từ Wikipedia / Wikimedia Commons** (thông qua API hoặc script kiểm tra) hoặc ảnh thực tế Google CDN.
  - Đối với Khách sạn, Nhà hàng, Chợ: Nếu chưa có ảnh xác thực riêng thì tạm thời để null hoặc tính sau theo nguồn xác thực riêng, **nghiêm cấm hành vi tái sử dụng một link ảnh cho nhiều khách sạn/địa điểm khác nhau để làm giả dữ liệu**.
- **Missing Data Fallback**: When `typical_time_spent` or `price_range` is null in the database, use the explicit heuristic fallbacks defined in `PROJECT_CONTEXT.md`. NEVER invent random arbitrary numbers.
- **Human Travel Rhythm (Bắt buộc theo nhịp sinh học)**:
  $$\text{Tham quan sáng} \rightarrow \text{Ăn trưa} \rightarrow \text{Nghỉ trưa / Check-in} \rightarrow \text{Tham quan chiều} \rightarrow \text{Cà phê} \rightarrow \text{Ăn tối} \rightarrow \text{Chợ đêm / Nghỉ ngơi}$$
  Never schedule 4 temples or museums consecutively.

---

## 4. Hotel Switching Rules (Quy tắc đổi khách sạn)

- Do not recommend hotel changes for minor distance differences ($< 20\text{ km}$).
- Only trigger hotel switching alerts when distance between days is substantial ($\ge 30 - 40\text{ km}$) and travel time saved outweighs check-in/out inconvenience.
- In multi-day trips (3-5 days), cap hotel changes at 1-2 times maximum to avoid hotel-hopping fatigue.

---

## 5. Room & Expense Allocation Rules

- Group accommodation calculations must account for room capacity:
  $$\text{Số phòng} = \lceil \text{Số người} / 2 \rceil$$
  *(Ví dụ: 4 người = 2 phòng đôi, không được nhân đơn giá phòng x 4).*
- Transportation fuel/parking is shared across the entire group, not multiplied per person.
