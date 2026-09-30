# KIẾN TRÚC ĐỊNH TUYẾN ĐA PHƯƠNG THỨC & ROAD TRIP ĐƯỜNG DÀI
## (Multi-Modal Transit, Gateway Airport & Long-Distance Road Trip Architecture)

> **Tài liệu Đặc tả Kiến trúc Kỹ thuật Chuẩn Top 0.1% (Principal Systems Architect Standard)**  
> **Dự án**: VNTravel AI (`vn-travel-planner`)  
> **Phạm vi**: Tối ưu hóa chuỗi hành trình cửa ngõ (Gateway Catchment), An toàn sinh học đường dài (Fatigue Constraints), và Phân luồng Định tuyến Đa phương thức.

---

## 1. Bối cảnh & Bản chất Bài toán Thế giới Thực (Problem Statement)

Hầu hết các hệ thống lập lịch trình du lịch hiện nay (kể cả các nền tảng thương mại lớn) đều mắc phải **3 sai lầm thế giới thực nghiêm trọng**:
1. **Ảo giác Cự ly Lớn (Long-Distance Spatial Illusion)**: Người dùng ở Hà Nội chọn đi Phú Quốc hoặc Đà Nẵng, hệ thống tự động tính xăng ô tô chạy 1.200 – 1.600 km liên tục, hoặc "nhảy cóc" người dùng đến bãi biển mà không mô hình hóa chặng trung chuyển hàng không/đường bộ thực tế.
2. **Bỏ quên Giới hạn Sinh học & An toàn Giao thông (Fatigue Disregard)**: Với người muốn tự lái xe cá nhân đi xa, hệ thống không tính toán thời gian ngồi sau vô lăng, thiếu các điểm dừng nghỉ ngơi sau mỗi 3–4 tiếng, thiếu điểm nghỉ đêm giữa chặng, tạo ra lịch trình bất khả thi về mặt thể lực.
3. **Độ dốc Địa hình & Điểm mù Thời tiết (Topographic & Weather Blindness)**: Áp dụng cùng một vận tốc đường nhựa đồng bằng cho đường đèo dốc sạt lở vùng cao, và lập lịch trình ngoài trời trong điều kiện bão lũ.

Tài liệu này đặc tả kiến trúc giải pháp toàn diện từ **Toán học Vận trù học (Operations Research)**, **Dữ liệu Thực địa Ground-Truth 100%**, đến **Data Contract chuẩn mực**.

---

## 2. Kiến trúc Tổng thể Hệ thống (End-to-End Pipeline)

```
                       KIẾN TRÚC ĐIỀU PHỐI ĐA PHƯƠNG THỨC
    
    ┌──────────────────────────────────────────────────────────────────┐
    │                 GIAO DIỆN TƯƠNG TÁC ĐỒNG BỘ 2 CHIỀU             │
    │  ┌─────────────────────────┐        ┌─────────────────────────┐  │
    │  │   Form Chọn Tham Số     │ ◄────► │   Prompt Tự Do (NLU)    │  │
    │  │  (Tỉnh, Người, Xe,...)  │        │ ("Gia đình 4 người...") │  │
    │  └────────────┬────────────┘        └────────────┬────────────┘  │
    └───────────────┼──────────────────────────────────┼───────────────┘
                    │                                  │
                    ▼                                  ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │             LỚP BÓC TÁCH NGỮ NGHĨA (AI SANDWICH - TOP LAYER)     │
    │   Pydantic Constrained JSON Decoding (Gemini Flash / Ollama Qwen)│
    └──────────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │         LÕI TỐI ƯU HÓA TOÁN HỌC XÁC ĐỊNH (CORE ENGINE)           │
    │                                                                  │
    │  [1. Tính Khoảng cách Trắc địa D(Origin -> Dest) qua Haversine] │
    │                                │                                 │
    │        ┌───────────────────────┴───────────────────────┐         │
    │        ▼ (D < 300 km: NỘI VÙNG)                        ▼ (D >= 300 km: LIÊN VÙNG)
    │  [Định tuyến Đường bộ Thuần túy]             Kiểm tra Mong muốn Phương tiện:
    │  - Tính theo Ma trận Địa hình               ┌──────────┴──────────┐
    │  - Bỏ qua trung chuyển hàng không           ▼                     ▼
    │                                     [Đi Máy Bay]        [Tự Lái Xe Đường Dài]
    │                                     - Gateway Catchment - Fatigue Evaluator (4h)
    │                                       (Radius 150km)    - Overnight Staging (8h)
    │                                     - 3-Piece Visual    - Anti-Boredom Loop
    └──────────────────────────────────────────────────────────────────┘
```

---

## 3. Kiến trúc AI: Local First với Qwen 2.5 7B (Ollama) & Gemini Fallback

Hệ thống thiết lập nguyên tắc **"Local-First Sovereign AI"** nhằm làm chủ công nghệ, tối ưu chi phí vận hành và đảm bảo tính học thuật cao nhất cho đề tài:

```
                          KIẾN TRÚC ĐIỀU PHỐI AI TỰ CHỦ
  
              [ Câu lệnh / Prompt Tự nhiên của Người dùng ]
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │   LÕI SỐ 1 (PRIMARY): Ollama Server (Local Port 11434) │
       │   Model: `vn-travel-qwen:7b` (Fine-tuned Qwen 2.5)     │
       │   - Structured Grammar / Pydantic JSON Output          │
       │   - Phục vụ Offline 100%, độc lập hoàn toàn Internet   │
       │   - Tốc độ suy luận cục bộ: 35 - 55 tokens/giây        │
       └────────────────────────────┬───────────────────────────┘
                                    │
                         (Thất bại / Timeout > 4s)
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │   LÕI SỐ 2 (FALLBACK): Google Gemini 2.0 Flash API     │
       │   - Kích hoạt tự động qua Circuit Breaker Resilience   │
       │   - Đảm bảo hệ thống KHÔNG BAO GIỜ sập dù tắt Ollama  │
       └────────────────────────────────────────────────────────┘
```

### 3.1. Đặc tả Huấn luyện Mô hình Miền: `vn-travel-qwen:7b`
- **Mục tiêu**: Biến mô hình nền `Qwen2.5-7B-Instruct` thành Chuyên gia Trích xuất Ngữ nghĩa Du lịch Việt Nam (Vietnam Travel Domain NLU & Explainer).
- **Bộ Dữ liệu Huấn luyện (Domain Dataset)**:
  - Sinh 300 – 500 cặp mẫu hội thoại du lịch thực tế dựa trên 1.369 địa danh và 34 tỉnh trong `travel_db.db`.
  - Bao phủ các trường hợp đa dạng: Tiếng lóng du lịch (*"phượt tứ đại đỉnh đèo"*, *"săn mây"*, *"ăn sập chợ đêm"*), các ràng buộc thể lực (*gia đình có con nhỏ*, *người lớn tuổi*), và phân định rõ ràng các nhịp sinh học (`COASTAL`, `HERITAGE`, `MOUNTAIN`).
- **Quy trình Fine-Tuning QLoRA (Unsloth on Colab T4)**:
  1. Base model: `Qwen/Qwen2.5-7B-Instruct-bnb-4bit`.
  2. Kỹ thuật: QLoRA với $r=16, \alpha=32$, mục tiêu module `q_proj, k_proj, v_proj, o_proj`.
  3. Thời gian train: $\approx 15 - 20\text{ phút}$ trên GPU T4 (miễn phí).
  4. Xuất bản: Merge LoRA weights và lượng tử hóa sang định dạng `q4_k_m.gguf` ($\approx 4.5\text{ GB}$).
- **Triển khai vào Ollama (Modelfile)**:
  ```dockerfile
  FROM ./vn-travel-qwen-7b-q4_k_m.gguf
  PARAMETER temperature 0.2
  PARAMETER stop "<|im_end|>"
  SYSTEM """Bạn là VNTravel AI - Chuyên gia hoạch định du lịch Việt Nam đỉnh cao. Nhiệm vụ của bạn là bóc tách mọi yêu cầu tự do của du khách thành cấu trúc JSON chuẩn mực, đồng thời giải thích thấu đáo các quyết định định tuyến dựa trên nhịp sinh học và an toàn giao thông."""
  ```

### 3.2. Circuit Breaker Fallback sang Cloud Gemini
- Backend Service (`app/services/llm_service.py`) ưu tiên bắn HTTP request tới `http://localhost:11434/api/chat`.
- Nếu kết nối bị từ chối (`ConnectionRefusedError`) hoặc quá thời gian chờ ($> 4\text{s}$), hệ thống tự động chuyển tiếp prompt sang **Google Gemini 2.0 Flash** với cùng một Pydantic Schema. Người dùng cuối và giao diện hoàn toàn không nhận thấy sự gián đoạn.

---

## 4. Bài toán 1: Hành trình Hàng không Khép kín (Door-to-Door Flight Pipeline)

### 4.1. Cơ sở Dữ liệu 22 Sân bay Dân dụng Chuẩn Xác Thực 100%
- Bảng `airports` trong `travel_db.db` lưu trữ đầy đủ 22 sân bay thương mại Việt Nam.
- Toàn bộ tọa độ GPS, Google Place ID, địa chỉ bưu chính và URL Google Maps đều được trích xuất từ thực địa, không có dữ liệu giả định.

### 4.2. Thuật toán Chọn Sân bay Cửa ngõ (Normalized Gateway Airport Scoring)
Đối với các điểm đến không có sân bay riêng (Hội An, Sa Pa, Ninh Bình, Phan Thiết, Mũi Né...):
1. Hệ thống lọc tất cả sân bay nằm trong bán kính khả dụng $R \le 150\text{ km}$.
2. Áp dụng **Hàm thỏa dụng đa tiêu chí đã chuẩn hóa không thứ nguyên (Normalized Multi-Criteria Utility Function)**:

$$\text{Score}(A) = w_1 \cdot \left(\frac{F(A) - F_{\min}}{F_{\max} - F_{\min}}\right) - w_2 \cdot \left(\frac{D(A, T) - D_{\min}}{D_{\max} - D_{\min}}\right)$$

*Trong đó*:
- $F(A)$: Tần suất khai thác chuyến bay/ngày của sân bay $A$.
- $D(A, T)$: Khoảng cách đường bộ từ sân bay $A$ đến điểm đến thực tế $T$.
- $w_1 = 0.4, w_2 = 0.6$: Trọng số tối ưu hóa thời gian di chuyển mặt đất.
- *Ví dụ thực tế*: Khách đi **Hội An**: Dù Chu Lai (VCL) thuộc Quảng Nam, nhưng Đà Nẵng (DAD, cách 30 km, tần suất 80 chuyến/ngày) đạt điểm số vượt trội so với Chu Lai (cách 80 km, 6 chuyến/ngày) $\implies$ Hệ thống tự động chọn DAD.

### 4.3. Mô hình Bản đồ 3 Mảnh ghép (3-Piece Route Visualization)
Tránh việc gọi Routing API đường bộ xuyên biển hoặc xuyên không:
- **Piece 1 (First-Mile Road)**: Vị trí xuất phát $\to$ Sân bay đi (Đường bộ Goong Maps / Taxi / Tuyến Bus).
- **Piece 2 (Air Transit Corridor)**: Cung trắc địa nối Sân bay đi $\to$ Sân bay đến (Đường bay nét đứt màu tím `#7C3AED`, không gọi Routing API).
- **Piece 3 (Last-Mile Road)**: Sân bay đến $\to$ Khách sạn tại điểm đích (Đường bộ Goong Maps / Thuê xe máy / Shuttle bus).

---

## 5. Bài toán 2: Long-Distance Road Trip & An toàn Sinh học

Khi cự ly liên tỉnh $D \ge 300\text{ km}$ và người dùng chủ động chọn phương tiện cá nhân (`car`, `motorbike`):

### 5.1. Ràng buộc An toàn & Thể lực (Fatigue Constraints)
- **Chu kỳ nghỉ ngơi bắt buộc (Pit-stop Rule)**: Cứ sau mỗi **3 – 3.5 giờ lái xe liên tục** (tương đương $160 - 200\text{ km}$), hệ thống bắt buộc chèn 1 trạm dừng chân 30–45 phút (đổ xăng, uống cafe, giãn cơ).
- **Trần giới hạn thể lực trong ngày (Daily Driving Cap)**: Tối đa **8 giờ lái xe/ngày** ($\le 450\text{ km}$ đường trường).
- **Phân chặng Nghỉ đêm Trung gian (Overnight Staging)**: Khi hành trình $> 650 - 700\text{ km}$ (ví dụ: Hà Nội $\leftrightarrow$ Đà Nẵng $\approx 780\text{ km}$):
  - Tự động tách chuyến đi thành 2 ngày di chuyển.
  - Tự động định vị điểm dừng chân nghỉ đêm tối ưu (như TP. Đồng Hới hoặc TP. Vinh) tại các khách sạn nằm trong bán kính $1\text{ km}$ quanh trục xuyên Việt, kèm bữa tối đặc sản địa phương.

### 5.2. Ma trận Vận tốc & Hệ số Địa hình Việt Nam (Topographic Terrain Matrix)
Nghiêm cấm dùng một hệ số uốn lượn và vận tốc cố định cho toàn bộ lãnh thổ:

| Loại hình Địa hình | Tỉnh tiêu biểu | Hệ số uốn lượn ($K_{\text{topo}}$) | Vận tốc Trung bình ($V_{\text{avg}}$) |
| :--- | :--- | :--- | :--- |
| **Đồng bằng / Trục Cao tốc** | Hà Nội, Bắc Ninh, Đà Nẵng, TP.HCM | $1.20 - 1.25$ | $70 - 90\text{ km/h}$ |
| **Bán sơn địa / Duyên hải** | Thanh Hóa, Nghệ An, Bình Định | $1.30 - 1.35$ | $55 - 65\text{ km/h}$ |
| **Đèo dốc Vùng cao / Tây Bắc** | Hà Giang, Lào Cai, Sơn La, Lâm Đồng | $1.65 - 1.85$ | $30 - 40\text{ km/h}$ |

$$\text{Estimated Travel Time} = \frac{D_{\text{Haversine}} \times K_{\text{topo}}}{V_{\text{avg}}} + \sum T_{\text{PitStops}}$$

### 5.3. Hai Chế độ Trải nghiệm Lái xe (Travel Persona)
- ⚡ **Express Mode (Cao tốc xuyên suốt)**: Ưu tiên trục cao tốc huyết mạch Bắc - Nam, thời gian di chuyển tối thiểu, trạm dừng chân chọn các trạm dịch vụ cao tốc chính thức.
- 🌄 **Scenic Discovery Mode (Cung đường Di sản & Ngắm cảnh)**:
  - Mở rộng hành lang đệm (Corridor Buffer $15\text{ km}$) quét các danh thắng ven đường trong `travel_db.db`.
  - Ưu tiên leo **Đèo Hải Vân** (ngắm vịnh Lăng Cô và Hải Vân Quan) thay vì chui hầm Hải Vân.

### 5.4. Lộ trình Vòng Khép kín Chống Trùng lặp (Anti-Boredom Loop)
- **Chiều Đi**: Tuyến ven biển / Cao tốc Quốc lộ 1A (Trải nghiệm biển và tốc độ).
- **Chiều Về**: Chuyển hướng sang trục **Đường mòn Hồ Chí Minh Tây / Quốc lộ 14** (Khám phá phong cảnh núi rừng đại ngàn, bản làng và di tích lịch sử chiến trường xưa).

---

## 6. Đặc tả Data Contract Chuẩn (API / Frontend Communication)

Để đảm bảo khả năng mở rộng không phụ thuộc giao diện, API `/api/plan/calculate` trả về cấu trúc phân tách rõ ràng cho 3 trạng thái hành trình:

```json
{
  "trip_mode": "MULTI_MODAL_FLIGHT" | "LONG_DISTANCE_ROAD_TRIP" | "LOCAL_EXPLORE",
  "flight_transit": {
    "is_flight_required": true,
    "first_mile": { "from": "Hà Nội", "to_airport": "HAN", "distance_km": 28.5, "mode": "taxi" },
    "air_corridor": { "origin_iata": "HAN", "dest_iata": "DAD", "est_flight_time_min": 80 },
    "last_mile": { "from_airport": "DAD", "to_hotel": "Khách sạn Hội An", "distance_km": 29.8, "mode": "shuttle" },
    "total_transit_cost_vnd": 3450000
  },
  "road_trip_staging": {
    "is_staging_required": true,
    "outbound_legs": [
      { "leg_day": 1, "start": "Hà Nội", "end_staging_city": "Đồng Hới", "distance_km": 490, "pit_stops": ["Trạm Cao tốc Ninh Bình", "Trạm dừng Nghệ An"] },
      { "leg_day": 2, "start": "Đồng Hới", "end_dest": "Đà Nẵng", "distance_km": 290, "pit_stops": ["Nghỉ chân Lăng Cô"] }
    ],
    "return_legs": [ ... ]
  },
  "destination_days": [
    { "day_number": 1, "date_theme": "Di sản Phố Cổ", "timeline": [ ... ] }
  ]
}
```

---

## 7. Kết luận & Giá trị Học thuật

1. **Khắc phục Triệt để Định kiến "Hệ thống Đồ chơi"**: Tách bạch toán học xác định và AI tạo sinh, giải quyết bài toán giao thông thực tế của Việt Nam với các tham số cự ly, trạm nghỉ, sân bay cửa ngõ có kiểm chứng 100%.
2. **Khả năng Mở rộng Module (Pluggable Architecture)**: Có thể tích hợp thêm dữ liệu vé tàu hỏa Bắc - Nam (Đường sắt Thống Nhất) hoặc phà cao tốc biển đảo (Rạch Giá $\leftrightarrow$ Phú Quốc, Trần Đề $\leftrightarrow$ Côn Đảo) một cách tự nhiên theo đúng mô hình 3 mảnh ghép này.
