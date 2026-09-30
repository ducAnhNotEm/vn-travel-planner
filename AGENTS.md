# TRAVEL AI - PROJECT RULES & AGENT GOVERNANCE

## 00. The Top 0.1% Elite Engineering Standard (Tiêu chuẩn Kỹ thuật Đỉnh cao Top 0.1%)

> **TÔN CHỈ BẮT BUỘC**: Mọi quyết định kiến trúc, giải thuật và dòng code trong dự án này **BẮT BUỘC phải đạt tư duy và chuẩn mực của Top 0.1% Kỹ sư Xuất sắc nhất trong ngành (Principal / Staff Systems Architect)**.
> Tuyệt đối cấm tư duy "làm cho chạy được", code chắp vá phong trào, hoặc sản phẩm dạng "bài tập lớn sinh viên thông thường".

### 5 Trụ Cột Thực Thi của Top 0.1%:
1. **Clean Architecture & Decoupled Modularization (Kiến trúc Sạch & Phân rã Độc lập)**:
   - Cấm viết code "Spaghetti", nhồi nhét hàm hàng trăm dòng hay lồng `if-else` chắp vá vào các file đang chạy ổn định.
   - Mọi tính năng lớn (Hàng không, Road Trip, Tối ưu hóa) phải được đóng gói thành các Service độc lập, có Data Contract (Pydantic Schema / Type Hints) rõ ràng, giao tiếp dạng Plug-and-Play.
2. **Defensive Design & Zero-Failure Resiliency (Thiết kế Phòng thủ & Chống sụp đổ tuyệt đối)**:
   - Luôn giả định mọi dịch vụ bên thứ ba (Goong Maps, Google APIs, LLMs) **đều có thể sập hoặc timeout bất kỳ lúc nào**.
   - Bắt buộc có cơ chế Caching (In-memory / MD5 file) và Fallback thông minh (ví dụ: rớt Goong API thì tự động fallback về Geodesic/Haversine, tuyệt đối không để crash 500 hay vỡ giao diện).
3. **Deterministic Mathematical Rigor over Stochastic AI (Toán học xác định trên hết)**:
   - LLM chỉ là lớp giao tiếp (NLU/NLG). Toàn bộ bài toán định tuyến, phân mảnh chặng, tính chi phí, phân bổ khách sạn bắt buộc phải giải bằng toán học và thuật toán xác định trên dữ liệu thực tế `travel_db.db`.
4. **Deep Real-World Domain Modeling (Mô hình hóa sâu sắc bản chất thế giới thực)**:
   - Không được ngô nghê: Phải mô hình hóa trọn vẹn giới hạn an toàn sinh học (Fatigue Constraint khi lái xe > 4h), nhịp sinh học theo vùng miền, phân luồng đa phương thức (First-mile, Transit, Last-mile), quét cửa ngõ liên tỉnh (Gateway Airport Radius 150km).
5. **Simplicity as the Ultimate Sophistication (Đỉnh cao của sự tinh tế là sự giản đơn)**:
   - Code của kỹ sư top đầu là code ít dòng nhất, ít dependency nhất, thanh thoát nhất nhưng giải quyết trọn vẹn bài toán lớn nhất.

---

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
- **Human Travel Rhythm (Bắt buộc theo nhịp sinh học du lịch Việt Nam)**:
  Hệ thống bắt buộc phải phân loại điểm đến để áp dụng chính xác 1 trong 3 nhịp sinh học chuẩn thực tế:
  
  1. 🌊 **Nhịp Sinh Học Du Lịch Biển (Coastal / Beach Rhythm)**:
     - 🌅 **05:30 - 07:00**: Đón bình minh bãi biển & Tắm biển sớm.
     - 🍜 **07:30 - 08:30**: Ăn sáng đặc sản địa phương (Bún cá, bánh canh...).
     - 🚶 **09:00 - 11:30**: Đi dạo / Tham quan danh thắng / Check-in mát mẻ.
     - 🍲 **11:45 - 13:00**: Ăn trưa hải sản / nhà hàng địa phương.
     - 🏨 **13:00 - 15:30**: **BẮT BUỘC NGHỈ TRƯA TRÁNH NẮNG GẮT TẠI KHÁCH SẠN** (Tuyệt đối không xếp hoạt động ngoài trời lúc nắng đỉnh điểm).
     - 🌇 **16:00 - 18:00**: Ngắm hoàng hôn trên biển / Bãi tắm chiều & Hoạt động thể thao nước.
     - 🚿 **18:00 - 18:45**: Về phòng tắm tráng nước ngọt & Lên đồ đi chơi tối.
     - 🦀 **19:00 - 20:30**: Ăn tối tiệc hải sản tươi sống.
     - 🌊 **20:45 - 22:30**: Đi dạo biển đêm tiếp / Chợ đêm ven biển / Cafe nghe sóng & nhạc Acoustic.

  2. 🏛️ **Nhịp Sinh Học Vùng Di Tích, Văn Hóa & Đồng Bằng / Đô Thị (Heritage & Urban Rhythm)**:
     - 🍜 **07:30 - 08:30**: Ăn sáng đặc sản (Phở, bún bò, bánh cuốn...).
     - 🏛️ **08:30 - 11:30**: Tham quan danh thắng chính / Di tích lịch sử / Đền chùa (Tranh thủ lúc trời mát, nắng chưa gắt).
     - 🍲 **11:45 - 13:00**: Ăn trưa đặc sản vùng miền.
     - 🏨 **13:00 - 14:30**: Nghỉ trưa tránh nắng (Khách sạn hoặc quán cafe điều hòa yên tĩnh).
     - 🛶 **14:45 - 17:00**: Trải nghiệm Làng nghề truyền thống / Đi thuyền sinh thái mát mẻ (Tràng An, Tam Cốc...).
     - ☕ **17:15 - 18:30**: Cafe view ngắm hoàng hôn / Dạo bờ hồ (Hồ Gươm, Hồ Tây, Sông Hương...).
     - 🍲 **19:00 - 20:30**: Ăn tối nhà hàng đặc sản.
     - 🏮 **20:45 - 22:30**: Phố đi bộ, Chợ đêm, xem biểu diễn nghệ thuật truyền thống.
     - ❌ **Cấm kỵ**: Tuyệt đối không xếp 3 - 4 di tích/chùa liên tiếp; cấm xếp leo núi/bậc thang ngoài trời nắng từ 12:30 - 14:30.

  3. 🌲 **Nhịp Sinh Học Vùng Đồi Núi & Cao Nguyên (Mountain / Highland Rhythm)**:
     - ☁️ **06:00 - 07:30**: Săn mây / Đón bình minh thung lũng trong không khí se lạnh.
     - ☕ **07:45 - 08:45**: Ăn sáng nóng hổi + Nhâm nhi cafe ngắm núi rừng.
     - 🚶 **09:00 - 11:30**: Check-in thác nước / Bản làng văn hóa / Trekking nhẹ.
     - 🍲 **11:45 - 13:15**: Ăn trưa cơm lam gà đồi, lợn bản nướng, rau rừng.
     - 🏨 **13:30 - 15:00**: Nghỉ ngơi tại homestay / resort.
     - 🌸 **15:00 - 17:30**: Dạo đồi thông, đồi chè, vườn hoa, ngắm hoàng hôn.
     - 🔥 **18:30 - 20:30**: Tiệc nướng than hoa / Lẩu nóng quây quần bên bếp lửa.
     - 🧣 **20:45 - 22:30**: Dạo chợ đêm vùng cao, uống sữa đậu nành nóng / Nghe nhạc Acoustic.

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

---

## 6. Graceful 4-Tier Fallback Rules (Đường lui 4 tầng khi thiếu dữ liệu)

Khi người dùng tìm kiếm địa điểm chung chung hoặc dịch vụ vi mô (quán net, bi-a, tiệm thuốc...) không có trong Database và Apify không cào được:
1. **Tầng 1 (Tra cứu DB & Apify)**: Ưu tiên tìm kiếm thực địa chính thức.
2. **Tầng 2 (Thay thế tương đương ngữ nghĩa - Semantic Substitution)**: Nếu không có điểm cụ thể, tự động gợi ý điểm giải trí/thư giãn cùng bản chất từ `travel_db.db` (rạp phim, trung tâm mua sắm, cafe boardgame) kèm lời giải thích thành thật.
3. **Tầng 3 (Chặng dừng Phố trung tâm - Commercial Hub)**: Đưa người dùng đến khu phố thương mại/chợ sầm uất nhất khu vực nơi các dịch vụ này tập trung để khách tự chọn.
4. **Tầng 4 (Thẻ Hoạt động Tự do + Nút Radar Google Maps)**: Giữ nguyên khung giờ trong Timeline dưới dạng `[Hoạt động tự do]`, tích hợp nút 1-chạm mở app Google Maps quét tìm dịch vụ xung quanh vị trí thực tế của khách. **TUYỆT ĐỐI KHÔNG BỊA ĐẶT ĐỊA DANH ẢO.**

---

## 7. Distance Outlier & Smart Advisory Rules (Cảnh báo Điểm quá xa)

- **Ngưỡng khoảng cách bất thường**: Khi một điểm phụ (quán cafe, quán ăn vặt, giải trí) cách cụm tham quan chính trong ngày $\ge 15 - 20\text{ km}$ ($> 35 - 45\text{ phút}$ di chuyển):
  - ❌ **CẤM** âm thầm nhét vào làm con thoi lịch trình, đội chi phí và làm kiệt sức du khách.
  - ✅ **BẮT BUỘC** kích hoạt Thẻ Lời khuyên Thông minh (Smart Advisory Card):
    1. **Minh bạch số liệu**: Nêu rõ số km chênh lệch, thời gian lái xe tốn thêm và chi phí phát sinh ước tính.
    2. **Phương án A (Khuyên dùng)**: Gợi ý điểm tương đương gần hơn trong bán kính $< 3\text{ km}$ của cụm ngày đó.
    3. **Phương án B (Tôn trọng khách)**: Nếu khách bắt buộc phải đi, tự động dời điểm đó về cuối ngày trên đường về khách sạn hoặc ghép sang ngày khác có tuyến đường tiện nhất.

---

## 8. Hard Pinned Day & Anchor-Based Clustering Rules (Ghim ngày cố định)

- Khi người dùng có yêu cầu bắt buộc ghé thăm một địa điểm vào một ngày/buổi cụ thể (Hard Constraint):
  - **Mệnh lệnh tối cao**: Thuật toán gom cụm **TUYỆT ĐỐI KHÔNG ĐƯỢC CHUYỂN** địa điểm ghim sang ngày khác.
  - **Hạt nhân thích ứng (Anchor-Based Adaptive Clustering)**: Lấy điểm ghim làm "Tâm hạt nhân" của Ngày $X$. Tự động hút các điểm tham quan/quán ăn lân cận điểm ghim về Ngày $X$ và đẩy các điểm xa sang ngày khác để tối ưu lộ trình.
  - **Cảnh báo xung đột**: Nếu người dùng ghim 2 điểm cách nhau $> 100\text{ km}$ vào cùng một ngày, hệ thống vẫn xếp theo lệnh nhưng bắt buộc hiện cảnh báo thời gian di chuyển trên cao tốc.

---

## 9. Multi-Modal Transit & Gateway Airport Catchment Rules (Hàng không Đa phương thức)

- **Ngưỡng Kích hoạt Hàng không**: Khi khoảng cách trắc địa liên tỉnh $D(\text{Origin}, \text{Destination}) \ge 300\text{ km}$:
  - Bắt buộc kiểm tra tính khả thi của đường bay trung chuyển.
- **Quy tắc Sân bay Cửa ngõ (Gateway Airport Catchment Area)**:
  - Với các điểm đến không có sân bay thương mại riêng (Hội An, Ninh Bình, Sa Pa, Mũi Né...): Quét các sân bay trong bán kính hành lang lân cận $R \le 150\text{ km}$.
  - Lựa chọn sân bay tối ưu bắt buộc dùng **Hàm thỏa dụng đa tiêu chí chuẩn hóa không thứ nguyên (Normalized Multi-Criteria Utility Function)** giữa tần suất chuyến bay $F(A)$ và cự ly đường bộ $D(A, T)$. Cấm lấy 2 đại lượng khác thứ nguyên trừ trực tiếp cho nhau.
- **Mô hình Bản đồ 3 Mảnh ghép (3-Piece Route Visualization)**:
  - First-mile (Đường bộ Goong) $\to$ Air Corridor (Cung trắc địa nối 2 sân bay, nét đứt tím `#7C3AED`) $\to$ Last-mile (Đường bộ Goong).
  - ❌ **TUYỆT ĐỐI CẤM** gọi Routing API đường bộ xuyên biển hoặc xuyên không gian giữa các tỉnh cách nhau hàng trăm km.

---

## 10. Long-Distance Road Trip Fatigue & Topographic Speed Rules (Road Trip & Địa hình)

- **Ràng buộc Mỏi mệt Sinh học (Fatigue Constraint)**:
  - Sau mỗi $3 - 3.5\text{ giờ}$ lái xe liên tục (hoặc $160 - 200\text{ km}$), bắt buộc chèn một trạm dừng nghỉ ngắn 30-45 phút (uống nước, đổ xăng).
  - Trần thể lực an toàn: Tối đa $8\text{ giờ}$ lái xe/ngày ($\le 450\text{ km}$).
  - Cự ly $\ge 650 - 700\text{ km}$: Bắt buộc tách thành hành trình nhiều ngày và chọn điểm dừng chân nghỉ đêm tối ưu (Overnight Staging City) sát trục giao thông chính.
- **Ma trận Vận tốc Địa hình Thực tế (Topographic Terrain Matrix)**:
  - Tuyệt đối cấm áp dụng một vận tốc cao tốc duy nhất cho toàn bộ địa hình Việt Nam:
    - **Đồng bằng / Cao tốc**: $K_{\text{topo}} = 1.20 - 1.25, V_{\text{avg}} = 70 - 90\text{ km/h}$.
    - **Bán sơn địa / Duyên hải**: $K_{\text{topo}} = 1.30 - 1.35, V_{\text{avg}} = 55 - 65\text{ km/h}$.
    - **Đèo dốc Vùng cao / Tây Bắc**: $K_{\text{topo}} = 1.65 - 1.85, V_{\text{avg}} = 30 - 40\text{ km/h}$.

---

## 11. Local-First AI Sovereign Architecture & Circuit Breaker Governance (Kiến trúc AI Tự chủ)

- **Tôn chỉ "Local First"**:
  - **LÕI SỐ 1 (PRIMARY)**: Máy chủ cục bộ **Ollama** (`http://localhost:11434`) chạy mô hình miền **`vn-travel-qwen:7b`** (fine-tuned trên nền Qwen 2.5 7B Instruct).
  - Đảm bảo tính tự chủ công nghệ, chạy Offline 100% không phụ thuộc Internet, bảo mật tuyệt đối dữ liệu cá nhân.
- **Cơ chế Phòng thủ Circuit Breaker**:
  - **LÕI SỐ 2 (FALLBACK)**: **Google Gemini 2.0 Flash API**.
  - Tự động kích hoạt khi kết nối Ollama bị từ chối (`ConnectionRefusedError`) hoặc thời gian phản hồi quá $4\text{ giây}$. Tuyệt đối không để ứng dụng bị crash hay treo vô tận.
- **Pydantic Structured Output Enforcement**:
  - Mọi phản hồi từ LLM bắt buộc phải được validate qua Pydantic Schema để triệt tiêu hoàn toàn rủi ro hallucination hoặc lỗi cú pháp JSON.

---

## 12. Operations Research Routing & Time-Window Standard (Chuẩn hóa Vận trù học)

- **Cấm bẫy Tham lam Cục bộ**: Với số điểm tham quan trong ngày ($N \le 10$), thay vì Nearest Neighbor thô sơ, bắt buộc áp dụng **2-Opt Local Search** hoặc **Held-Karp Dynamic Programming** để loại bỏ triệt để các cung đường cắt chéo.
- **Ràng buộc Khung thời gian Cứng (Hard Time-Window Scheduling)**:
  - Khung giờ tham quan của mỗi điểm phải thỏa mãn nghiêm ngặt giờ mở/đóng cửa (`working_hours` trong `travel_db.db`):
    $$\text{Arrival Time}_i + \text{Dwell Time}_i + \text{Travel Time}_{i,j} \le \text{Close Time}_j$$
  - Nghiêm cấm xếp các điểm mở cửa muộn (chợ đêm, phố đi bộ) lên trước chỉ vì khoảng cách gần khách sạn.

---

## 13. Actionable 1-Click Hand-off & Export Standard (Xuất bản Lộ trình Thực tế)

- Hệ thống phải cung cấp giá trị thực chiến cho người dùng sau khi lập lịch:
  - **Google Maps Multi-Stop Navigation URL**: Tự động sinh link mở thẳng ứng dụng Google Maps với toàn bộ các chặng dừng trong ngày (`https://www.google.com/maps/dir/Origin/Stop1/Stop2/.../Hotel`).
  - **Lịch số (iCal / Google Calendar)**: Chuẩn hóa xuất file `.ics` đồng bộ toàn bộ mốc giờ check-in, ăn uống, tham quan kèm thông báo nhắc trước 15 phút.


