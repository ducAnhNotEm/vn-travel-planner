# 🛡️ CLAUDE 3.5 SONNET ARCHITECTURAL & DATASET AUDIT PACKAGE
## Dự Án: Travel AI Planner Việt Nam — NLU Fine-Tuning Specification (Schema v3 & v4)

> **MỤC TIÊU CỦA TÀI LIỆU**:  
> Cung cấp toàn bộ ngữ cảnh kiến trúc, khế ước dữ liệu (Data Contract), 7 Định luật Bất biến (Invariants) và các mẫu đối kháng thực tế để **Claude 3.5 Sonnet** thực hiện đợt thẩm định chuyên sâu (Adversarial Review) trước khi tiến hành sinh tập dữ liệu 6.000+ mẫu JSONL huấn luyện mô hình Qwen 2.5 7B.

---

## PHẦN 1: BỐI CẢNH KIẾN TRÚC & PHÂN TẦNG HỆ THỐNG (AI SANDWICH)

Hệ thống Travel AI Việt Nam được xây dựng theo mô hình **AI Sandwich (Top 0.1% Standard)**:
1. **Lớp Trên Cùng (Top Layer - NLU Parser)**: Mô hình Qwen 2.5 7B (Fine-tuned bằng LoRA/Unsloth).
   - **Vai trò tối cao**: **Thuần túy là một SEMANTIC PARSER**, tuyệt đối **KHÔNG PHẢI LÀ DECISION MAKER**.
   - Chỉ trích xuất sự thật (Facts & Entities) từ câu nói của người dùng thành JSON chuẩn Schema v3.
   - Không được tự ý nhẩm cự ly, không được tự suy diễn số ngày/ngân sách/phương tiện nếu khách không nói.
2. **Lớp Giữa (Middle Layer - Deterministic Python Engine)**:
   - Cơ sở dữ liệu: `travel_db.db` gồm **2.396 địa danh thực tế** chuẩn Google Places, 34 tỉnh thành, 22 sân bay.
   - Giải thuật: Định tuyến 2-Opt TSPTW, nhịp sinh học du lịch (Biển / Đô thị / Núi), Goong Maps Polyline thực tế, phân chia phòng khách sạn ($\lceil \text{người}/2 \rceil$).
3. **Lớp Dưới Cùng (Bottom Layer - NLG Explainer)**:
   - Dùng Claude 4.6 / Qwen để thuyết minh tự nhiên quyết định thuật toán cho người dùng (giải thích tại sao đổi khách sạn, cảnh báo lái xe quá 4h mỏi mệt).

---

## PHẦN 2: KHẾ ƯỚC DỮ LIỆU SCHEMA v3 (15 FIELDS)

Mọi bản ghi JSON đầu ra của NLU bắt buộc tuân theo thứ tự `KEY_ORDER`:
```json
{
  "intent": "plan_itinerary | search_place | ask_advisory | clarify_needed",
  "destination": "Tên tỉnh/thành chuẩn hoặc null",
  "destination_regions": ["Danh sách vùng: NORTH, NORTHWEST, NORTHEAST, RED_RIVER_DELTA, NORTH_CENTRAL, CENTRAL, SOUTH_CENTRAL, CENTRAL_HIGHLANDS, SOUTH, SOUTHEAST, MEKONG_DELTA"],
  "terrain_types": ["Danh sách địa hình: BEACH, ISLAND, MOUNTAIN, HIGHLAND, FOREST, CAVE, RIVER"],
  "excluded_destinations": ["Danh sách tỉnh/thành bị người dùng loại trừ"],
  "excluded_places": ["Danh sách địa danh cụ thể bị loại trừ"],
  "origin": "Tên tỉnh/thành xuất phát, sân bay, hoặc 'CURRENT_LOCATION'",
  "duration_days": "Số nguyên ngày hoặc null",
  "group_size": "Số nguyên người hoặc null",
  "vehicle_type": "car | motorbike | plane | train | coach hoặc null",
  "budget_total_vnd": "Số nguyên VND hoặc null",
  "preferences": ["Sở thích, mong muốn của du khách"],
  "excluded_activities": ["Các hoạt động bị người dùng từ chối: không ăn hải sản, tránh leo dốc..."],
  "hard_pinned_locations": ["Các địa điểm bắt buộc ghé thăm được người dùng ghim cứng"],
  "prefer_flight": "true | false | null"
}
```

---

## PHẦN 3: 7 ĐỊNH LUẬT BẤT BIẾN (THE 7 INVARIANTS)

1. **Rule 1 (Zero Semantic Mutation):** NLU ghi nhận nguyên văn sự thật. Nếu khách nói *"16 người đi ô tô 4 chỗ"* $\to$ NLU trả về `group_size: 16, vehicle_type: "car"`. Việc xe quá tải thuộc quyền xử lý của **Constraint Engine** sau đó, NLU không tự sửa thành `"van"`.
2. **Rule 2 (`null` là Không có dữ liệu, KHÔNG PHẢI Hệ thống tự quyết):** `prefer_flight: null` chỉ có nghĩa là người dùng không đề cập máy bay. Backend không được coi đó là cho phép tự bay.
3. **Rule 3 (Intent $\neq$ Completeness):** Câu *"Lên tour Đà Nẵng 3 ngày"* có intent rõ ràng là `plan_itinerary`. Dù thiếu `origin` hay `group_size`, NLU không được hạ cấp thành `clarify_needed`.
4. **Rule 4 (`CURRENT_LOCATION` là Reference Token):** Khi user nói *"từ chỗ tôi"*, *"từ đây"*, NLU trả về token `"CURRENT_LOCATION"`. Context Resolver sẽ chịu trách nhiệm phân giải toạ độ GPS.
5. **Rule 5 (Business Defaults nằm ngoài NLU):** NLU không gán giá trị mặc định (`group_size = 2` hay `days = 2`). Không có dữ liệu thì bắt buộc để `null`.
6. **Rule 6 (Conditional Request $\neq$ Preference):** Câu *"Nếu có hoa tam giác mạch thì đi Hà Giang"* là một điều kiện (Condition). NLU không được nhét bừa vào `preferences: ["hoa tam giác mạch"]`.
7. **Rule 7 (Quy Tắc Vùng Miền vs Điểm Cụ Thể):**
   - Khi khách nói địa danh cụ thể (*"Đi Hội An"*, *"Đi Phú Quốc"*): `destination = "Đà Nẵng"` hoặc `"Kiên Giang"`; `destination_regions = []`, `terrain_types = []`.
   - Khi khách nói trừu tượng (*"Đi biển miền Trung"*, *"Đi núi Tây Bắc"*): `destination = null`; điền đúng mã enum vào `destination_regions` và `terrain_types`.

---

## PHẦN 4: 15 MẪU DỮ LIỆU ĐỐI KHÁNG THỰC TẾ (REPRESENTATIVE SAMPLES)

### Ca 1: Bẫy Đảo Ngữ Cực Đoan (Inversion)
* **User**: *"Tới Quảng Nam đi bằng máy bay xuất phát từ Bắc Ninh, 4 ngày 3 đêm cho 2 người"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": "Quảng Nam",
  "destination_regions": [],
  "terrain_types": [],
  "excluded_destinations": [],
  "excluded_places": [],
  "origin": "Bắc Ninh",
  "duration_days": 4,
  "group_size": 2,
  "vehicle_type": "plane",
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": [],
  "hard_pinned_locations": [],
  "prefer_flight": true
}
```

### Ca 2: Trừu Tượng Hóa Vùng Miền & Địa Hình (Region & Terrain)
* **User**: *"Tạo lịch trình du lịch núi phía Bắc cho 2 người xuất phát từ HN"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": null,
  "destination_regions": ["NORTH"],
  "terrain_types": ["MOUNTAIN"],
  "excluded_destinations": [],
  "excluded_places": [],
  "origin": "Hà Nội",
  "duration_days": null,
  "group_size": 2,
  "vehicle_type": null,
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": [],
  "hard_pinned_locations": [],
  "prefer_flight": null
}
```

### Ca 3: Phủ Định Cấp Tỉnh (Excluded Destinations)
* **User**: *"Tư vấn tour miền Trung 5 ngày cho 4 người đi ô tô từ Huế, trừ Đà Nẵng ra vì đi rồi"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": null,
  "destination_regions": ["CENTRAL"],
  "terrain_types": [],
  "excluded_destinations": ["Đà Nẵng"],
  "excluded_places": [],
  "origin": "Huế",
  "duration_days": 5,
  "group_size": 4,
  "vehicle_type": "car",
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": [],
  "hard_pinned_locations": [],
  "prefer_flight": null
}
```

### Ca 4: Phủ Định Cấp Điểm & Hoạt Động (Excluded Places & Activities)
* **User**: *"Đi Nha Trang 3N2Đ từ Sài Gòn, không đi Vinpearl, không tắm bùn và không ăn hải sản"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": "Khánh Hòa",
  "destination_regions": [],
  "terrain_types": [],
  "excluded_destinations": [],
  "excluded_places": ["Vinpearl"],
  "origin": "Hồ Chí Minh",
  "duration_days": 3,
  "group_size": null,
  "vehicle_type": null,
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": ["không tắm bùn", "không ăn hải sản"],
  "hard_pinned_locations": [],
  "prefer_flight": null
}
```

### Ca 5: Ghim Địa Danh Cứng (Hard Pinned)
* **User**: *"Đi Đà Nẵng 3 ngày từ Cần Thơ, ngày 1 nhất định phải ghé Bãi biển Mỹ Khê và Chợ Đêm Sơn Trà"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": "Đà Nẵng",
  "destination_regions": [],
  "terrain_types": [],
  "excluded_destinations": [],
  "excluded_places": [],
  "origin": "Cần Thơ",
  "duration_days": 3,
  "group_size": null,
  "vehicle_type": null,
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": [],
  "hard_pinned_locations": ["Bãi biển Mỹ Khê", "Chợ Đêm Sơn Trà"],
  "prefer_flight": null
}
```

### Ca 6: Token Tham Chiếu Vị Trí Hiện Tại (Reference Token)
* **User**: *"Từ chỗ tôi đi Vũng Tàu 2 ngày cuối tuần bằng xe máy thì hết bao nhiêu tiền?"*
* **Target JSON**:
```json
{
  "intent": "plan_itinerary",
  "destination": "Hồ Chí Minh",
  "destination_regions": [],
  "terrain_types": [],
  "excluded_destinations": [],
  "excluded_places": [],
  "origin": "CURRENT_LOCATION",
  "duration_days": 2,
  "group_size": null,
  "vehicle_type": "motorbike",
  "budget_total_vnd": null,
  "preferences": ["cuối tuần"],
  "excluded_activities": [],
  "hard_pinned_locations": [],
  "prefer_flight": null
}
```

### Ca 7: Yêu Cầu Cộc Lốc / Mơ Hồ (Clarify Needed)
* **User**: *"Đi chơi 3 ngày"*
* **Target JSON**:
```json
{
  "intent": "clarify_needed",
  "destination": null,
  "destination_regions": [],
  "terrain_types": [],
  "excluded_destinations": [],
  "excluded_places": [],
  "origin": null,
  "duration_days": 3,
  "group_size": null,
  "vehicle_type": null,
  "budget_total_vnd": null,
  "preferences": [],
  "excluded_activities": [],
  "hard_pinned_locations": [],
  "prefer_flight": null
}
```

---

## PHẦN 5: BỘ CÂU HỎI THẨM VẤN CHUYÊN SÂU DÀNH CHO CLAUDE 3.5 SONNET

Khi gửi tài liệu này cho **Claude 3.5 Sonnet**, hãy yêu cầu Claude trả lời 5 câu hỏi kiến trúc sau:

1. **Khả Năng Phá Vỡ Schema (Schema Robustness)**:  
   *Trong văn nói tự nhiên của người Việt, có những cấu trúc câu nào (như câu đa mệnh đề, câu phủ định kép, từ lóng địa phương) có thể gây nhầm lẫn giữa `destination` cụ thể và `excluded_destinations` hoặc `hard_pinned_locations` không?*

2. **Ranh Giới Semantic Parser vs Decision Maker**:  
   *Quy tắc 7 Invariants đã thực sự ngăn chặn triệt để tình trạng LLM tự suy diễn (hallucination) chưa? Còn trường hợp nào LLM có thể vô tình "lấn sân" sang nghiệp vụ của Backend Constraint Engine không?*

3. **Cơ Chế Phân Định Vùng Miền (Regions/Terrains)**:  
   *Quy tắc: 'Khi có destination cụ thể thì destination_regions và terrain_types bắt buộc để []' có điểm mù nào không? Ví dụ khách nói: 'Tôi muốn đi biển Nha Trang' — việc đặt terrain_types = [] và đưa 'biển' vào preferences có gây mất mát thông tin địa hình cho bộ lọc sau đó không?*

4. **Tỷ Lệ Phân Bổ Dataset 6.000 Mẫu**:  
   *Với mục tiêu huấn luyện Qwen 2.5 7B (QLoRA 4-bit qua Unsloth trên Colab T4), tỷ lệ phân bổ:*
   - *Plan Itinerary: ~40%*
   - *Adversarial (Đảo ngữ, loại trừ): ~25%*
   - *Search Place: ~20%*
   - *Regions/Terrain: ~7%*
   - *Advisory & Clarify: ~8%*  
   *đã tối ưu để mô hình vừa ghi nhớ 2.396 địa danh thật vừa không bị hiện tượng Catastrophic Forgetting hay học vẹt (overfitting) chưa?*

5. **Chiến Lược Đánh Giá (Evaluation Protocol)**:  
   *Cần bổ sung những Metric đánh giá chuyên biệt nào (ngoài JSON syntax accuracy và F1-score thực thể) để đo lường chính xác tỷ lệ vi phạm khế ước (Contract Violation Rate) trên tập Test Set?*
